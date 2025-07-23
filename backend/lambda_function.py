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

def lambda_handler(event, context):
    """
    Main Lambda handler for website status checking
    """
    try:
        # CORS preflight
        if event.get('httpMethod') == 'OPTIONS':
            return cors_response(200, {})

        # Parse URL from POST body
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
        url = body.get('url') or event.get('url')
        if not url:
            return cors_response(400, {'error': 'URL is required'})

        if not is_valid_url(url):
            return cors_response(400, {'error': 'Invalid URL format'})

        # Core status check
        result = check_website_status(url)

        # External free monitoring (no paid services)
        ext = get_external_status_checks(url)
        if ext:
            result['external_checks'] = ext

        return cors_response(200, result)

    except Exception as e:
        print(f"Error: {e}")
        return cors_response(500, {'error': 'Internal server error'})


def check_website_status(url):
    """
    Check website status from this region
    """
    region = os.environ.get('AWS_REGION', 'unknown')
    start_time = time.time()

    # Ensure protocol
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)

    # 1) DNS
    dns = check_dns_resolution(host)
    # 2) HTTP
    http = check_http_response(url)
    # 3) Port
    port_chk = check_port_connectivity(host, port)

    elapsed_ms = round((time.time() - start_time) * 1000, 2)
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


def check_http_response(url):
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
        return {'status': 'timeout', 'error': 'Request timed out'}
    except requests.exceptions.RequestException as e:
        return {'status': 'error', 'error': str(e)}


def check_port_connectivity(domain, port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        start = time.time()
        ok = sock.connect_ex((domain, port)) == 0
        rt = round((time.time() - start) * 1000, 2)
        sock.close()
        return {'port': port, 'status': 'open' if ok else 'closed', 'response_time_ms': rt}
    except Exception as e:
        return {'port': port, 'status': 'error', 'error': str(e)}


def get_external_status_checks(url):
    """
    Free external checks: downforeveryoneorjustme, isitdownrightnow, websiteplanet
    """
    try:
        cached = get_cached_external_result(url)
        if cached:
            return cached

        checks = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            futures = {
                ex.submit(check_downforeveryoneorjustme, url): 'downforeveryoneorjustme',
                ex.submit(check_isitdownrightnow, url): 'isitdownrightnow',
                ex.submit(check_websiteplanet, url): 'websiteplanet'
            }
            for f in concurrent.futures.as_completed(futures, timeout=5):
                svc = futures[f]
                try:
                    r = f.result(timeout=3)
                    if r:
                        checks[svc] = r
                except Exception as e:
                    checks[svc] = {'status': 'error', 'error': str(e)}

        if checks:
            cache_external_result(url, checks)
        return checks

    except Exception as e:
        print(f"External checks error: {e}")
        return None


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


def check_isitdownrightnow(url):
    domain = urlparse(url).netloc
    try:
        r = requests.head(f"http://{domain}", timeout=3, allow_redirects=True)
        return {'status': 'up' if r.status_code < 400 else 'down', 'status_code': r.status_code}
    except:
        return {'status': 'down', 'error': 'Connection failed'}


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


def determine_overall_status(checks):
    dns_ok = checks['dns']['overall_status'] == 'success'
    http_ok = checks['http']['status'] == 'success'
    port_ok = checks['port']['status'] == 'open'
    if http_ok:
        return 'up'
    if dns_ok and port_ok:
        return 'partial'
    if dns_ok:
        return 'dns_only'
    return 'down'


def generate_status_summary(checks):
    parts = []
    parts.append("DNS OK" if checks['dns']['overall_status'] == 'success' else "DNS fail")
    http_st = checks['http'].get('status', 'unknown')
    parts.append("HTTP OK" if http_st == 'success' else http_st)
    parts.append("Port open" if checks['port']['status'] == 'open' else "Port closed")
    return "; ".join(parts)


def get_cached_external_result(url):
    """
    Read from DynamoDB (local if DYNAMODB_ENDPOINT is set).
    """
    try:
        params = {}
        endpoint = os.getenv('DYNAMODB_ENDPOINT')
        if endpoint:
            params['endpoint_url'] = endpoint
        dynamodb = boto3.resource('dynamodb', **params)
        table = dynamodb.Table(os.environ.get('CACHE_TABLE_NAME', 'website-status-cache'))
        resp = table.get_item(Key={'url': url, 'type': 'external'})
        item = resp.get('Item')
        if item:
            cache_time = datetime.fromisoformat(item['timestamp'])
            if datetime.utcnow() - cache_time < timedelta(minutes=5):
                return item['data']
        return None
    except ClientError as e:
        print(f"DynamoDB ClientError: {e.response['Error']['Message']}")
        return None
    except Exception:
        return None


def cache_external_result(url, data):
    """
    Write to DynamoDB (local if DYNAMODB_ENDPOINT is set).
    """
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


def is_valid_url(url):
    try:
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        p = urlparse(url)
        return p.scheme in ('http', 'https') and p.netloc != ''
    except:
        return False


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


def multi_region_check(event, context):
    """
    Handler for multi-region orchestration
    """
    try:
        body = json.loads(event.get('body', '{}')) if event.get('body') else {}
        url = body.get('url')
        if not url:
            return cors_response(400, {'error': 'URL is required'})

        local = check_website_status(url)
        other_regions = os.environ.get('OTHER_REGIONS', '').split(',')
        other_results = []

        if other_regions and other_regions[0]:
            client = boto3.client('lambda')
            for r in other_regions:
                if r.strip():
                    try:
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

        all_res = [local] + other_results
        up = sum(1 for x in all_res if x.get('status') in ('up', 'partial'))
        total = len(all_res)
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
