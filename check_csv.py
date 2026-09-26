import pandas as pd
df = pd.read_csv('data/traffic/traffic_observations.csv')
print('CSV latest observed_at:', df["observed_at"].max())
print('CSV earliest observed_at:', df["observed_at"].min())
print('CSV rows:', len(df))
print('CSV unique links:', df["link_id"].nunique())