import pandas as pd
path = r"plans/NPFL ALL-TIME DATABASE.xlsx"
try:
    df = pd.read_excel(path, sheet_name=0)
    print('ROWS:', len(df))
    print('COLUMNS:', list(df.columns))
    print('\nSAMPLE ROWS:')
    print(df.head(10).to_dict(orient='records'))
except Exception as e:
    print('ERROR:', e)
