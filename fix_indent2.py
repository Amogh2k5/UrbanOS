with open(r'C:\projects\UrbanOS\backend\app\overview\api.py', 'r') as f:
    content = f.read()

# Fix the indentation around the deduplication section
old = '''        # Deduplicate alerts: use (domain, title, timestamp) as key
        # Prefer stable event IDs when available
        seen = set()
        deduped_alerts = []
        sys.stderr.write(f"DEBUG: all_alerts before dedup = {len(all_alerts)}\\n")
        sys.stderr.flush()
        for alert in all_alerts:
            # Use alert id if available, otherwise create composite key
            alert_id = alert.get("id") or alert.get("alert_id") or alert.get("alert_id")
            if alert_id:
                key = (alert.get("domain", ""), str(alert_id))
            else:
                key = (
                    alert.get("domain", ""),
                    alert.get("title", "")[:50],
                    alert.get("timestamp", "")[:20],
                )
            if key not in seen:
                seen.add(key)
                deduped_alerts.append(alert)
        
        # Sort by timestamp descending, take top 10
        deduped_alerts.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        top_alerts = deduped_alerts[:10]
        sys.stderr.write(f"DEBUG: top_alerts = {len(top_alerts)}\\n")
        sys.stderr.flush()'''

new = '''    # Deduplicate alerts: use (domain, title, timestamp) as key
    # Prefer stable event IDs when available
    seen = set()
    deduped_alerts = []
    sys.stderr.write(f"DEBUG: all_alerts before dedup = {len(all_alerts)}\\n")
    sys.stderr.flush()
    for alert in all_alerts:
        # Use alert id if available, otherwise create composite key
        alert_id = alert.get("id") or alert.get("alert_id") or alert.get("alert_id")
        if alert_id:
            key = (alert.get("domain", ""), str(alert_id))
        else:
            key = (
                alert.get("domain", ""),
                alert.get("title", "")[:50],
                alert.get("timestamp", "")[:20],
            )
        if key not in seen:
            seen.add(key)
            deduped_alerts.append(alert)
        
        # Sort by timestamp descending, take top 10
        deduped_alerts.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        top_alerts = deduped_alerts[:10]'''

if old in content:
    content = content.replace(old, new)
    with open(r'C:\projects\UrbanOS\backend\app\overview\api.py', 'w') as f:
        f.write(content)
    print("Fixed!")
else:
    print("Pattern not found")