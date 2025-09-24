from datetime import datetime

def get_season_from_date(date_str: str) -> str:
    parsed = None
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d'):
        try:
            parsed = datetime.strptime(date_str, fmt)
            break
        except Exception:
            continue
    if parsed is None:
        parsed = datetime.fromisoformat(date_str)
    month = parsed.month
    if 6 <= month <= 10:
        return 'Kharif'
    elif month == 11 or month <= 3:
        return 'Rabi'
    else:
        return 'Zaid'

def get_season_months(season: str) -> str:
    s = str(season).strip().lower()
    if s == 'kharif':
        return 'June–October (sowing: June–July, harvesting: Sept–Nov)'
    if s == 'rabi':
        return 'November–March (sowing: Oct–Dec, harvesting: Feb–Apr)'
    if s == 'zaid':
        return 'April–May (sowing: Apr–May, harvesting: Jul–Aug)'
    return ''
