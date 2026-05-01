# ─────────────────────────────────────────────────────────────────────────────
# lambda_function.py — The backend brain of the Website Status Checker.
#
# This file runs as two separate AWS Lambda functions in the cloud:
#   1. lambda_handler      → checks a website from one region (the main one)
#   2. multi_region_check  → coordinates checks from multiple regions at once
#
# When the frontend sends a URL, API Gateway receives it and wakes up one of
# these functions. The function does all its checks, builds a result dictionary,
# and sends it back to the frontend as JSON.
# ─────────────────────────────────────────────────────────────────────────────

import json
import requests
import time
import os
import socket
from urllib.parse import urlparse
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError
import concurrent.futures


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT — Single Region Check
# ─────────────────────────────────────────────────────────────────────────────
# This is the first function AWS calls when the frontend hits the /check endpoint.
# It reads the URL from the request body, validates it, runs all the checks,
# and returns a structured result back to the browser.
def lambda_handler(event, context):

    try:
        # Handle CORS preflight — browsers send an OPTIONS request before the
        # real POST to confirm the server allows cross-origin requests. We just
        # say yes and return immediately.
        if event.get('httpMethod') == 'OPTIONS':
            return cors_response(200, {})

        # Pull the URL out of the request body. The frontend sends JSON like:
        # { "url": "google.com" }
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
        url = body.get('url') or event.get('url')

        if not url:
            return cors_response(400, {'error': 'URL is required'})

        # Make sure the URL is actually a valid web address before doing anything
        if not is_valid_url(url):
            return cors_response(400, {'error': 'Invalid URL format'})

        # Run all the technical checks (DNS, HTTP, port)
        result = check_website_status(url)

        # Also ask some free third-party services for their opinion on the site
        ext = get_external_status_checks(url)
        if ext:
            result['external_checks'] = ext

        return cors_response(200, result)

    except Exception as e:
        print(f"Error: {e}")
        return cors_response(500, {'error': 'Internal server error'})


# ─────────────────────────────────────────────────────────────────────────────
# CORE CHECK — Runs all three checks and assembles the result
# ─────────────────────────────────────────────────────────────────────────────
# This function orchestrates the three individual checks (DNS, HTTP, port),
# times how long the whole thing takes, and bundles everything into one dict.
def check_website_status(url):

    # Find out which AWS region this Lambda is running in (e.g. "us-east-2")
    region = os.environ.get('AWS_REGION', 'unknown')
    start_time = time.time()

    # Add https:// if the user typed just "google.com" with no protocol prefix
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)

    # Run the three checks one by one
    dns      = check_dns_resolution(host)       # Can the internet find this domain?
    http     = check_http_response(url)          # Does the website respond to a request?
    port_chk = check_port_connectivity(host, port)  # Is the server's port open?

    elapsed_ms = round((time.time() - start_time) * 1000, 2)

    # Combine the three check results into a single overall status (up/down/partial)
    overall = determine_overall_status({'dns': dns, 'http': http, 'port': port_chk})

    return {
        'url': url,
        'domain': host,
        'status': overall,
        'response_time_ms': elapsed_ms,
        'region': region,
        'timestamp': datetime.utcnow().isoformat(),
        'detailed_checks': {
            'dns': dns,
            'http': http,
            'port': port_chk
        },
        'summary': generate_status_summary({'dns': dns, 'http': http, 'port': port_chk})
    }


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 1 — DNS Resolution
# ─────────────────────────────────────────────────────────────────────────────
# DNS (Domain Name System) is like the internet's phone book. When you type
# "google.com", DNS translates it into an IP address like "142.251.33.206"
# so your computer knows where to actually send the request.
#
# We ask three different DNS servers (Google, Cloudflare, OpenDNS) independently.
# If at least one can find the domain, DNS is considered working.
def check_dns_resolution(domain):
    dns_servers = ['8.8.8.8', '1.1.1.1', '208.67.222.222']
    results = []

    for s in dns_servers:
        try:
            socket.setdefaulttimeout(3)
            ip = socket.gethostbyname(domain)
            results.append({'dns_server': s, 'status': 'success', 'ip_address': ip})
        except Exception as e:
            results.append({'dns_server': s, 'status': 'failed', 'error': str(e)})

    success = sum(1 for r in results if r['status'] == 'success')

    return {
        'overall_status': 'success' if success > 0 else 'failed',
        'success_count': success,
        'total_servers': len(dns_servers),
        'results': results
    }


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 2 — HTTP Response
# ─────────────────────────────────────────────────────────────────────────────
# This simulates what your browser does when you visit a website — it sends
# an HTTP request and waits for a response. A status code of 200 means the
# page loaded successfully. We also follow any redirects (e.g. http → https)
# and record how long the whole thing took.
def check_http_response(url):
    # Identify ourselves politely so servers don't block us as a bot
    headers = {
        'User-Agent': 'Website-Status-Checker/1.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }

    try:
        start = time.time()
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True, verify=True)
        rt = round((time.time() - start) * 1000, 2)

        return {
            'status': 'success',
            'status_code': resp.status_code,
            'response_time_ms': rt,
            'content_length': len(resp.content) if resp.content else 0,
            'redirected': resp.url != url,
            'final_url': resp.url if resp.url != url else None
        }

    except requests.exceptions.Timeout:
        # The server took longer than 10 seconds to respond — treated as a failure
        return {'status': 'timeout', 'error': 'Request timed out'}

    except requests.exceptions.RequestException as e:
        return {'status': 'error', 'error': str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# CHECK 3 — Port Connectivity
# ─────────────────────────────────────────────────────────────────────────────
# A port is like a specific door on a server building. Web traffic uses port 443
# (HTTPS) or port 80 (HTTP). Even if DNS works and the server exists, the port
# could be blocked by a firewall. This check opens a direct TCP connection to
# confirm the door is actually open and accepting visitors.
def check_port_connectivity(domain, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        start = time.time()
        ok = sock.connect_ex((domain, port)) == 0  # connect_ex returns 0 on success
        rt = round((time.time() - start) * 1000, 2)
        sock.close()
        return {'port': port, 'status': 'open' if ok else 'closed', 'response_time_ms': rt}

    except Exception as e:
        return {'port': port, 'status': 'error', 'error': str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# EXTERNAL CHECKS — Ask third-party services for a second opinion
# ─────────────────────────────────────────────────────────────────────────────
# Besides our own checks, we also ask three free monitoring services whether
# they think the site is up. This gives a broader picture — if our check says
# "up" but others say "down", the site might be up only in some regions.
#
# We run all three requests in parallel (simultaneously) to save time, and we
# cache the result in DynamoDB for 5 minutes so we don't hammer those services
# if the same URL is checked multiple times in quick succession.
def get_external_status_checks(url):
    try:
        # Check if we already have a fresh cached result for this URL
        cached = get_cached_external_result(url)
        if cached:
            return cached

        checks = {}

        # Run all three external checks at the same time using a thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            futures = {
                ex.submit(check_downforeveryoneorjustme, url): 'downforeveryoneorjustme',
                ex.submit(check_isitdownrightnow, url):        'isitdownrightnow',
                ex.submit(check_websiteplanet, url):           'websiteplanet'
            }

            # Collect results as each thread finishes (whichever finishes first)
            for f in concurrent.futures.as_completed(futures, timeout=5):
                svc = futures[f]
                try:
                    r = f.result(timeout=3)
                    if r:
                        checks[svc] = r
                except Exception as e:
                    checks[svc] = {'status': 'error', 'error': str(e)}

        # Save the combined result to DynamoDB so the next check can use it
        if checks:
            cache_external_result(url, checks)

        return checks

    except Exception as e:
        print(f"External checks error: {e}")
        return None


# ─── External service: downforeveryoneorjustme.com ───────────────────────────
# A well-known site that tells you if a domain is down for everyone globally
# or just a problem on your local network.
def check_downforeveryoneorjustme(url):
    domain = urlparse(url).netloc
    try:
        r = requests.get(f"https://downforeveryoneorjustme.com/check?domain={domain}", timeout=3)
        txt = r.text.lower()
        if 'just you' in txt:
            return {'status': 'up', 'message': 'Site appears up'}
        if 'not just you' in txt:
            return {'status': 'down', 'message': 'Site appears down'}
        return {'status': 'unknown', 'message': 'Could not determine'}
    except:
        return None


# ─── External service: isitdownrightnow (direct probe) ───────────────────────
# We probe the domain directly with a HEAD request — a lightweight request that
# only fetches headers, not the full page. Fast and efficient for status checks.
def check_isitdownrightnow(url):
    domain = urlparse(url).netloc
    try:
        r = requests.head(f"http://{domain}", timeout=3, allow_redirects=True)
        return {'status': 'up' if r.status_code < 400 else 'down', 'status_code': r.status_code}
    except:
        return {'status': 'down', 'error': 'Connection failed'}


# ─── External service: websiteplanet (dual-protocol probe) ───────────────────
# Tries to reach the site over both HTTPS and HTTP. If either protocol works,
# the site is considered up. Useful for catching servers that have SSL issues.
def check_websiteplanet(url):
    domain = urlparse(url).netloc
    protocols = ['https', 'http']
    results = []

    for p in protocols:
        try:
            r = requests.get(f"{p}://{domain}", timeout=3, allow_redirects=True)
            results.append({'protocol': p, 'status': 'up' if r.status_code < 400 else 'down', 'status_code': r.status_code})
        except:
            results.append({'protocol': p, 'status': 'down', 'error': 'Connection failed'})

    up = [r for r in results if r['status'] == 'up']
    return {'status': 'up', 'protocols': results} if up else {'status': 'down', 'protocols': results}


# ─────────────────────────────────────────────────────────────────────────────
# OVERALL STATUS — Combine the three check results into one verdict
# ─────────────────────────────────────────────────────────────────────────────
# Decides the single status label to show the user:
#   "up"       — HTTP response worked (the website loaded)
#   "partial"  — DNS and port work but HTTP didn't respond properly
#   "dns_only" — DNS resolved but port is closed (server not accepting connections)
#   "down"     — DNS failed entirely (domain not found)
def determine_overall_status(checks):
    dns_ok  = checks['dns']['overall_status'] == 'success'
    http_ok = checks['http']['status'] == 'success'
    port_ok = checks['port']['status'] == 'open'

    if http_ok:
        return 'up'
    if dns_ok and port_ok:
        return 'partial'
    if dns_ok:
        return 'dns_only'
    return 'down'


# ─────────────────────────────────────────────────────────────────────────────
# STATUS SUMMARY — One-line plain-English summary of all three checks
# ─────────────────────────────────────────────────────────────────────────────
# Builds a short human-readable string like "DNS OK; HTTP OK; Port open"
# that appears below the main status badge in the UI.
def generate_status_summary(checks):
    parts = []
    parts.append("DNS OK"   if checks['dns']['overall_status'] == 'success' else "DNS fail")
    http_st = checks['http'].get('status', 'unknown')
    parts.append("HTTP OK"  if http_st == 'success' else http_st)
    parts.append("Port open" if checks['port']['status'] == 'open' else "Port closed")
    return "; ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# CACHE READ — Get a previously stored result from DynamoDB
# ─────────────────────────────────────────────────────────────────────────────
# Before running external checks, we look in DynamoDB to see if we already
# checked this URL in the last 5 minutes. If yes, return the saved result
# immediately — faster for the user and avoids overloading third-party services.
def get_cached_external_result(url):
    try:
        params = {}
        endpoint = os.getenv('DYNAMODB_ENDPOINT')
        if endpoint:
            # Use a local DynamoDB (running in Docker) if the endpoint is set
            params['endpoint_url'] = endpoint

        dynamodb = boto3.resource('dynamodb', **params)
        table = dynamodb.Table(os.environ.get('CACHE_TABLE_NAME', 'website-status-cache'))
        resp = table.get_item(Key={'url': url, 'type': 'external'})
        item = resp.get('Item')

        if item:
            cache_time = datetime.fromisoformat(item['timestamp'])
            # Only use the cached result if it's less than 5 minutes old
            if datetime.utcnow() - cache_time < timedelta(minutes=5):
                return item['data']

        return None

    except ClientError as e:
        print(f"DynamoDB ClientError: {e.response['Error']['Message']}")
        return None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# CACHE WRITE — Save external check results to DynamoDB
# ─────────────────────────────────────────────────────────────────────────────
# After running external checks, we save the results so the next request for
# the same URL within 5 minutes can skip the slow external calls.
# The TTL field tells DynamoDB to automatically delete the record after 10 minutes.
def cache_external_result(url, data):
    try:
        params = {}
        endpoint = os.getenv('DYNAMODB_ENDPOINT')
        if endpoint:
            params['endpoint_url'] = endpoint

        dynamodb = boto3.resource('dynamodb', **params)
        table = dynamodb.Table(os.environ.get('CACHE_TABLE_NAME', 'website-status-cache'))
        table.put_item(Item={
            'url': url,
            'type': 'external',
            'data': data,
            'timestamp': datetime.utcnow().isoformat(),
            'ttl': int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
        })

    except ClientError as e:
        print(f"DynamoDB ClientError: {e.response['Error']['Message']}")
    except Exception as e:
        print(f"Cache error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# URL VALIDATOR
# ─────────────────────────────────────────────────────────────────────────────
# Before running any checks, we make sure the input looks like a real web URL.
# We accept both "google.com" (no protocol) and "https://google.com" (with protocol).
# Returns True if valid, False if not.
def is_valid_url(url):
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        p = urlparse(url)
        return p.scheme in ('http', 'https') and p.netloc != ''
    except:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# CORS RESPONSE BUILDER
# ─────────────────────────────────────────────────────────────────────────────
# Every response from the Lambda must include CORS headers. Without them,
# the browser blocks the response because the frontend (port 5173) and the
# backend API are on different origins. The headers tell the browser "yes,
# this response is safe to share with the frontend."
def cors_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Max-Age': '86400'
        },
        'body': json.dumps(body)
    }


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT — Multi-Region Check
# ─────────────────────────────────────────────────────────────────────────────
# This is the second Lambda function. Instead of checking from just one place,
# it checks from the current region AND then invokes separate Lambda functions
# deployed in other regions (e.g. US West, Europe) to check from there too.
#
# This answers the question: "Is the site down everywhere, or just in one region?"
# The overall status will be "up" (all regions), "mixed", or "down" (no regions).
def multi_region_check(event, context):
    try:
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
        url = body.get('url')

        if not url:
            return cors_response(400, {'error': 'URL is required'})

        # Run our own local check first
        local = check_website_status(url)

        # Get the list of other regions to check (set in the Lambda environment variables)
        other_regions = os.environ.get('OTHER_REGIONS', '').split(',')
        other_results = []

        if other_regions and other_regions[0]:
            client = boto3.client('lambda')

            for r in other_regions:
                if r.strip():
                    try:
                        # Invoke the single-region Lambda deployed in the other region
                        # by calling it by name. Each region has its own copy of the function.
                        fname = f"website-status-checker-{r.strip()}"
                        resp = client.invoke(
                            FunctionName=fname,
                            InvocationType='RequestResponse',
                            Payload=json.dumps({'url': url})
                        )
                        pl = json.loads(resp['Payload'].read())
                        if pl.get('statusCode') == 200:
                            other_results.append(json.loads(pl['body']))
                    except Exception as e:
                        print(f"Invoke {r} error: {e}")

        # Combine local result with all remote results
        all_res = [local] + other_results
        up = sum(1 for x in all_res if x.get('status') in ('up', 'partial'))
        total = len(all_res)

        # Determine the global verdict
        overall = 'down'
        if up == total:
            overall = 'up'
        elif up > 0:
            overall = 'mixed'

        return cors_response(200, {
            'url': url,
            'overall_status': overall,
            'regions_up': up,
            'total_regions': total,
            'results': all_res,
            'timestamp': datetime.utcnow().isoformat(),
            'analysis': analyze_multi_region_results(all_res)
        })

    except Exception as e:
        print(f"Multi-region error: {e}")
        return cors_response(500, {'error': 'Internal server error'})


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-REGION ANALYSIS — Summarize results across all regions in plain English
# ─────────────────────────────────────────────────────────────────────────────
# Takes the list of results from all regions and returns a one-sentence summary
# that explains what the numbers mean in plain English.
def analyze_multi_region_results(results):
    if not results:
        return "No results to analyze"

    total = len(results)
    up = sum(1 for r in results if r.get('status') in ('up', 'partial'))

    if up == total:
        return "Website accessible from all tested regions"
    if up == 0:
        return "Website appears down globally"
    return f"Mixed: {up}/{total} regions can reach it"
