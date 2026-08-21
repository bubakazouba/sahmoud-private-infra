import csv, json, os

def parse_csv(filepath):
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    lines = content.split('\n')
    header_idx = None
    for i, l in enumerate(lines):
        if 'Account' in l and 'Symbol' in l:
            header_idx = i
            break
    reader = csv.DictReader(lines[header_idx:])
    rows = list(reader)
    lots = []
    for r in rows:
        sym = r.get('Symbol/CUSIP', '').strip().strip('"')
        qty_s = r.get('Quantity', '').strip().strip('"').replace(',','')
        if not sym or not qty_s or qty_s in ('-',''):
            continue
        try:
            qty_f = float(qty_s)
        except:
            continue
        def parse_num(key):
            s = r.get(key, '').strip().strip('"').replace(',','').replace('$','')
            if not s or s in ('-',' - ',''):
                return 0.0
            try:
                return float(s)
            except:
                return 0.0
        mv_key = next((k for k in r.keys() if 'Market value' in k), None)
        stg_key = next((k for k in r.keys() if 'Short term' in k), None)
        ltg_key = next((k for k in r.keys() if 'Long term' in k), None)
        tg_key = next((k for k in r.keys() if 'Total gain' in k), None)
        mv = parse_num(mv_key) if mv_key else 0.0
        stg = parse_num(stg_key) if stg_key else 0.0
        ltg = parse_num(ltg_key) if ltg_key else 0.0
        tg = parse_num(tg_key) if tg_key else 0.0
        cost_per = parse_num('Cost per share')
        total_cost = parse_num('Total cost')
        is_short = stg != 0.0 and ltg == 0.0
        lot = {
            'symbol': sym,
            'description': r.get('Description', '').strip().strip('"'),
            'acquired': r.get('Acquired date', '').strip().strip('"'),
            'method': r.get('Cost basis method', '').strip().strip('"'),
            'qty': qty_f,
            'costPerShare': round(cost_per, 4),
            'totalCost': round(total_cost, 2),
            'mv': round(mv, 2),
            'stGain': round(stg, 2),
            'ltGain': round(ltg, 2),
            'totalGain': round(tg, 2),
            'covered': r.get('Covered/Non-covered', '').strip().strip('"'),
            'isShortTerm': is_short,
        }
        lots.append(lot)
    return lots

fifo = parse_csv("C:/users/bubakazouba/chat-assistant/state/downloads/costbasisdownload_3721 (1).csv")
hifo = parse_csv("C:/users/bubakazouba/chat-assistant/state/downloads/costbasisdownload_3721 (2).csv")
mintax = parse_csv("C:/users/bubakazouba/chat-assistant/state/downloads/costbasisdownload_3721 (3).csv")

total_mv = sum(l['mv'] for l in fifo)
total_cost = sum(l['totalCost'] for l in fifo)
total_ltg = sum(l['ltGain'] for l in fifo)
total_stg = sum(l['stGain'] for l in fifo)

amzn_lots = [
    {'symbol':'AMZN','description':'Amazon.com Inc','broker':'Fidelity','acquired':'2026-04-15','qty':428,'costPerShare':248.08,'totalCost':round(428*248.08,2),'mv':116707.04,'isShortTerm':True,'stGain':round(116707.04-428*248.08,2),'ltGain':0.0,'totalGain':round(116707.04-428*248.08,2),'ltCrossDate':'2027-04-15','covered':'Covered'},
    {'symbol':'AMZN','description':'Amazon.com Inc','broker':'Fidelity','acquired':'2025-10-15','qty':453,'costPerShare':215.80,'totalCost':round(453*215.80,2),'mv':123524.04,'isShortTerm':True,'stGain':round(123524.04-453*215.80,2),'ltGain':0.0,'totalGain':round(123524.04-453*215.80,2),'ltCrossDate':'2026-10-15','covered':'Covered'},
    {'symbol':'AMZN','description':'Amazon.com Inc','broker':'Fidelity','acquired':'2025-04-15','qty':423,'costPerShare':180.59,'totalCost':round(423*180.59,2),'mv':115343.64,'isShortTerm':False,'stGain':0.0,'ltGain':round(115343.64-423*180.59,2),'totalGain':round(115343.64-423*180.59,2),'ltCrossDate':None,'covered':'Covered'},
    {'symbol':'AMZN','description':'Amazon.com Inc','broker':'Fidelity','acquired':'2024-10-15','qty':340,'costPerShare':186.50,'totalCost':round(340*186.50,2),'mv':92711.20,'isShortTerm':False,'stGain':0.0,'ltGain':round(92711.20-340*186.50,2),'totalGain':round(92711.20-340*186.50,2),'ltCrossDate':None,'covered':'Covered'},
    {'symbol':'AMZN','description':'Amazon.com Inc','broker':'Fidelity','acquired':'2023-10-16','qty':115,'costPerShare':131.84,'totalCost':round(115*131.84,2),'mv':31358.20,'isShortTerm':False,'stGain':0.0,'ltGain':round(31358.20-115*131.84,2),'totalGain':round(31358.20-115*131.84,2),'ltCrossDate':None,'covered':'Covered'},
]

amzn_mv = sum(l['mv'] for l in amzn_lots)
amzn_cost = sum(l['totalCost'] for l in amzn_lots)

brackets_2026 = {
    'source': 'Rev. Proc. 2025-32 / Notice 2025-67',
    'stdDeduction': 15000,
    'ordinaryBrackets': [
        {'rate': 0.10, 'min': 0, 'max': 11925},
        {'rate': 0.12, 'min': 11925, 'max': 48475},
        {'rate': 0.22, 'min': 48475, 'max': 103350},
        {'rate': 0.24, 'min': 103350, 'max': 197300},
        {'rate': 0.32, 'min': 197300, 'max': 250525},
        {'rate': 0.35, 'min': 250525, 'max': 626350},
        {'rate': 0.37, 'min': 626350, 'max': None},
    ],
    'ltcgBrackets': [
        {'rate': 0.00, 'min': 0, 'max': 48475},
        {'rate': 0.15, 'min': 48475, 'max': 533400},
        {'rate': 0.20, 'min': 533400, 'max': None},
    ],
    'caOrdinaryBrackets': [
        {'rate': 0.01, 'min': 0, 'max': 10756},
        {'rate': 0.02, 'min': 10756, 'max': 25499},
        {'rate': 0.04, 'min': 25499, 'max': 40245},
        {'rate': 0.06, 'min': 40245, 'max': 55866},
        {'rate': 0.08, 'min': 55866, 'max': 70606},
        {'rate': 0.093, 'min': 70606, 'max': 360659},
        {'rate': 0.103, 'min': 360659, 'max': 432787},
        {'rate': 0.113, 'min': 432787, 'max': 721314},
        {'rate': 0.123, 'min': 721314, 'max': 1000000},
        {'rate': 0.133, 'min': 1000000, 'max': None},
    ],
    'caLtcgIsOrdinary': True,
    'caStdDeduction': 5540,
    'ltcg0PctCeiling': 48475,
    'niitThreshold': 200000,
    'niitRate': 0.038,
}

data = {
    'generated': '2026-05-09',
    'mvDate': '2026-05-08',
    'vanguardLots': {
        'FIFO': fifo,
        'HIFO': hifo,
        'MinTax': mintax,
    },
    'amznLots': amzn_lots,
    'summary': {
        'vanguardLotsCount': len(fifo),
        'vanguardMV': round(total_mv, 2),
        'vanguardCost': round(total_cost, 2),
        'vanguardLTGain': round(total_ltg, 2),
        'vanguardSTGain': round(total_stg, 2),
        'amznLotsCount': len(amzn_lots),
        'amznMV': round(amzn_mv, 2),
        'amznCost': round(amzn_cost, 2),
        'totalBrokerageMV': round(total_mv + amzn_mv, 2),
        'k401Estimate': 600000,
        'rothIraEstimate': 100000,
        'statedTotalWealth': 2500000,
        'gapNote': 'Stated total $2.5M vs brokerage+401k+Roth ~$1.8M — $0.7M gap unreconciled; Empower lookup in flight',
    },
    'taxBrackets': brackets_2026,
}

os.makedirs("C:/Users/bubakazouba/sahmoud-private-infra/apps/tax-strategy/static", exist_ok=True)
with open("C:/Users/bubakazouba/sahmoud-private-infra/apps/tax-strategy/static/data.json", 'w') as f:
    json.dump(data, f, indent=2)

print("OK")
print(f"Vanguard: {len(fifo)} lots, MV=${total_mv:,.0f}")
print(f"AMZN: {len(amzn_lots)} lots, MV=${amzn_mv:,.0f}")
print(f"Total brokerage MV: ${total_mv+amzn_mv:,.0f}")
