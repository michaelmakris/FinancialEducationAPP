"""
What the market-data pipelines load. Edit this file to add a stock, coin or
indicator -- the jobs pick it up on the next run.

LEIs link a Euronext Athens ticker to its ESEF annual reports on
filings.xbrl.org; None means the issuer has no ESEF filing there yet (or
changed legal entity, e.g. OPAP -> Allwyn AG), so it gets prices only.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Euronext Athens equities (Yahoo symbols). Sector names follow ICB loosely.
# ---------------------------------------------------------------------------
GREEK_EQUITIES = [
    # ticker,       name,                                    sector,              LEI
    ("ETE.AT",      "National Bank of Greece",               "Banks",             "5UMCZOEYKCVFAW8ZLO05"),
    ("EUROB.AT",    "Eurobank",                              "Banks",             "JEUVK5RWVJEN8W0C9M24"),
    ("ALPHA.AT",    "Alpha Bank",                            "Banks",             "5299009N55YRQC69CN08"),
    ("TPEIR.AT",    "Piraeus Financial Holdings",            "Banks",             "M6AD1Y1KW32H8THQ6F76"),
    ("BOCHGR.AT",   "Bank of Cyprus Holdings",               "Banks",             "635400L14KNHZXPUZM19"),
    ("OPTIMA.AT",   "Optima Bank",                           "Banks",             "2138008NSD1X1XFUK750"),
    ("CREDIA.AT",   "CrediaBank",                            "Banks",             None),
    ("EXAE.AT",     "Euronext Athens Holding",               "Financial Services", "549300GSRN07MNENPL97"),
    ("HTO.AT",      "Hellenic Telecommunications (OTE)",     "Telecommunications", "ELPUFM0XZRZO4LFXW404"),
    ("PPC.AT",      "Public Power Corporation",              "Utilities",         "213800T9Y5XCOVRZ4Y57"),
    ("ADMIE.AT",    "ADMIE Holding",                         "Utilities",         None),
    ("EYDAP.AT",    "Athens Water Supply & Sewerage",        "Utilities",         "213800SA1M6NZ4YSQU91"),
    ("MOH.AT",      "Motor Oil Hellas",                      "Energy",            "213800U3Y9UL7Y4QVM11"),
    ("ELPE.AT",     "HELLENiQ ENERGY",                       "Energy",            "213800YUBJMZYR1SNG35"),
    ("MTLN.AT",     "Metlen Energy & Metals",                "Industrials",       "213800KT8MEUJEJ2KW41"),
    ("GEKTERNA.AT", "GEK TERNA",                             "Industrials",       "2138003TO2MTRHWVP686"),
    ("AKTR.AT",     "Aktor Holding",                         "Industrials",       None),
    ("AVAX.AT",     "Avax",                                  "Industrials",       "213800ZU3OTKF9M41394"),
    ("ELLAKTOR.AT", "Ellaktor",                              "Industrials",       "213800VUQHMOGEWKNG87"),
    ("CENER.AT",    "Cenergy Holdings",                      "Industrials",       "549300P50MFNOHG4U221"),
    ("VIO.AT",      "Viohalco",                              "Basic Materials",   "549300U0BOLVY36TGJ31"),
    ("ELHA.AT",     "ElvalHalcor",                           "Basic Materials",   "213800EYWS2GY56AWP42"),
    ("TITC.AT",     "Titan Cement International",            "Construction Materials", "213800H2CDP9I374WH83"),
    ("AEGN.AT",     "Aegean Airlines",                       "Travel & Leisure",  "213800VI8OH5EJM18L21"),
    ("ATTICA.AT",   "Attica Holdings",                       "Travel & Leisure",  "213800HBUHCXKIPIYO13"),
    ("ALWN.AT",     "Allwyn (formerly OPAP)",                "Travel & Leisure",  None),
    ("BELA.AT",     "Jumbo",                                 "Retail",            "549300TGIVUUMY40MZ05"),
    ("FOYRK.AT",    "Fourlis Holdings",                      "Retail",            "213800V54ASIMZREDX49"),
    ("SAR.AT",      "Sarantis",                              "Personal Care",     "21380078FJXYHFE8KP46"),
    ("KRI.AT",      "Kri-Kri Milk Industry",                 "Food & Beverage",   None),
    ("LAMDA.AT",    "Lamda Development",                     "Real Estate",       "213800C7PQZVF38FYL54"),
    ("QUEST.AT",    "Quest Holdings",                        "Technology",        "549300GTDOPCSETABE37"),
    ("PROF.AT",     "Profile Systems & Software",            "Technology",        "21380051TUVZ3KYK5G44"),
    ("ACAG.AT",     "Austriacard Holdings",                  "Technology",        "529900QI445M00DK4407"),
    ("INTRK.AT",    "Intracom Holdings",                     "Technology",        None),
]

# Indices / benchmarks loaded alongside (asset_type="index" / "etf").
BENCHMARKS = [
    ("GD.AT",     "Athens General Composite Index", "Index", "index", "GR", "EUR"),
    ("^STOXX50E", "EURO STOXX 50",                  "Index", "index", "",   "EUR"),
    ("^GSPC",     "S&P 500",                        "Index", "index", "US", "USD"),
    ("URTH",      "iShares MSCI World ETF",         "Global Equity", "etf", "US", "USD"),
]

# ---------------------------------------------------------------------------
# Crypto: Binance EUR pair for OHLCV, CoinGecko id for market cap / rank.
# Tickers are "<BASE>-EUR" so they never collide with the simulated demo's "BTC".
# ---------------------------------------------------------------------------
CRYPTO_ASSETS = [
    # ticker,      name,        binance pair, coingecko id
    ("BTC-EUR",  "Bitcoin",      "BTCEUR",  "bitcoin"),
    ("ETH-EUR",  "Ethereum",     "ETHEUR",  "ethereum"),
    ("SOL-EUR",  "Solana",       "SOLEUR",  "solana"),
    ("XRP-EUR",  "XRP",          "XRPEUR",  "ripple"),
    ("BNB-EUR",  "BNB",          "BNBEUR",  "binancecoin"),
    ("ADA-EUR",  "Cardano",      "ADAEUR",  "cardano"),
    ("DOGE-EUR", "Dogecoin",     "DOGEEUR", "dogecoin"),
    ("LINK-EUR", "Chainlink",    "LINKEUR", "chainlink"),
    ("DOT-EUR",  "Polkadot",     "DOTEUR",  "polkadot"),
    ("AVAX-EUR", "Avalanche",    "AVAXEUR", "avalanche-2"),
    ("LTC-EUR",  "Litecoin",     "LTCEUR",  "litecoin"),
    ("TRX-EUR",  "TRON",         "TRXEUR",  "tron"),
]

# ---------------------------------------------------------------------------
# Indicators. `snapshot` turns on the daily indicator_snapshots row (ported from
# the Databricks macro notebook): dead_band = |change| below which the 90-day
# direction is "stable"; staleness_cap_d = max age (from the END of the reference
# period) at which the latest value is still payload-eligible; comparator = the
# EU-27 series used as value_eu.
# ---------------------------------------------------------------------------
_EL = {"geo": "EL"}
_EU = {"geo": "EU27_2020"}

INDICATORS = [
    # --- Greece: prices, labour, growth (Eurostat)
    dict(id="hicp_yoy", name="Greece HICP inflation, % y/y", geo="EL", unit="pct_yoy", frequency="M", category="macro",
         source="eurostat", dataset="prc_hicp_minr", filters={**_EL, "coicop18": "TOTAL", "unit": "RCH_A"},
         snapshot=dict(dead_band=0.2, staleness_cap_d=60), comparator="hicp_yoy_eu"),
    dict(id="hicp_yoy_eu", name="EU-27 HICP inflation, % y/y", geo="EU27_2020", unit="pct_yoy", frequency="M", category="macro",
         source="eurostat", dataset="prc_hicp_minr", filters={**_EU, "coicop18": "TOTAL", "unit": "RCH_A"}),
    dict(id="unemp", name="Greece unemployment rate, % (SA)", geo="EL", unit="pct", frequency="M", category="macro",
         source="eurostat", dataset="une_rt_m", filters={**_EL, "s_adj": "SA", "sex": "T", "age": "TOTAL", "unit": "PC_ACT"},
         snapshot=dict(dead_band=0.2, staleness_cap_d=60), comparator="unemp_eu"),
    dict(id="unemp_eu", name="EU-27 unemployment rate, % (SA)", geo="EU27_2020", unit="pct", frequency="M", category="macro",
         source="eurostat", dataset="une_rt_m", filters={**_EU, "s_adj": "SA", "sex": "T", "age": "TOTAL", "unit": "PC_ACT"}),
    dict(id="youth_unemp", name="Greece youth (<25) unemployment rate, % (SA)", geo="EL", unit="pct", frequency="M", category="macro",
         source="eurostat", dataset="une_rt_m", filters={**_EL, "s_adj": "SA", "sex": "T", "age": "Y_LT25", "unit": "PC_ACT"},
         snapshot=dict(dead_band=0.5, staleness_cap_d=60)),
    dict(id="gdp_qoq", name="Greece real GDP, % q/q (SCA)", geo="EL", unit="pct_qoq", frequency="Q", category="macro",
         source="eurostat", dataset="namq_10_gdp", filters={**_EL, "unit": "CLV_PCH_PRE", "s_adj": "SCA", "na_item": "B1GQ"},
         snapshot=dict(dead_band=0.2, staleness_cap_d=120), comparator="gdp_qoq_eu"),
    dict(id="gdp_qoq_eu", name="EU-27 real GDP, % q/q (SCA)", geo="EU27_2020", unit="pct_qoq", frequency="Q", category="macro",
         source="eurostat", dataset="namq_10_gdp", filters={**_EU, "unit": "CLV_PCH_PRE", "s_adj": "SCA", "na_item": "B1GQ"}),
    dict(id="hh_saving", name="Greece household gross saving rate, %", geo="EL", unit="pct", frequency="Q", category="macro",
         source="eurostat", dataset="nasq_10_ki", filters={**_EL, "unit": "PC", "s_adj": "SCA", "na_item": "SRG_S14_S15", "sector": "S14_S15"},
         snapshot=dict(dead_band=0.2, staleness_cap_d=220)),
    dict(id="gov_debt_gdp", name="Greece general government debt, % of GDP", geo="EL", unit="pct_gdp", frequency="Q", category="macro",
         source="eurostat", dataset="gov_10q_ggdebt", filters={**_EL, "unit": "PC_GDP", "sector": "S13", "na_item": "GD"},
         snapshot=dict(dead_band=1.0, staleness_cap_d=220)),
    dict(id="consumer_conf", name="Greece consumer confidence indicator (balance, SA)", geo="EL", unit="balance", frequency="M", category="sentiment",
         source="eurostat", dataset="ei_bsco_m", filters={**_EL, "indic": "BS-CSMCI", "s_adj": "SA", "unit": "BAL"},
         snapshot=dict(dead_band=2.0, staleness_cap_d=60)),
    # --- Rates & FX (ECB)
    dict(id="ecb_dfr", name="ECB deposit facility rate, %", geo="U2", unit="pct", frequency="D", category="rates",
         source="ecb", key="FM/D.U2.EUR.4F.KR.DFR.LEV", snapshot=dict(dead_band=0.10, staleness_cap_d=7)),
    dict(id="estr", name="Euro short-term rate (€STR), %", geo="U2", unit="pct", frequency="D", category="rates",
         source="ecb", key="EST/B.EU000A2X2A25.WT", snapshot=dict(dead_band=0.10, staleness_cap_d=7)),
    dict(id="euribor_3m", name="3-month Euribor, % (monthly avg)", geo="U2", unit="pct", frequency="M", category="rates",
         source="ecb", key="FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA", snapshot=dict(dead_band=0.10, staleness_cap_d=45)),
    dict(id="ggb_10y", name="Greece 10y government bond yield, % (Maastricht)", geo="GR", unit="pct", frequency="M", category="rates",
         source="ecb", key="IRS/M.GR.L.L40.CI.0000.EUR.N.Z", snapshot=dict(dead_band=0.10, staleness_cap_d=60)),
    dict(id="bund_10y", name="Germany 10y government bond yield, % (Maastricht)", geo="DE", unit="pct", frequency="M", category="rates",
         source="ecb", key="IRS/M.DE.L.L40.CI.0000.EUR.N.Z"),
    dict(id="spread_10y", name="Greece-Germany 10y yield spread, bps", geo="GR", unit="bps", frequency="M", category="rates",
         source="derived", formula=("ggb_10y", "bund_10y", 100.0), snapshot=dict(dead_band=10.0, staleness_cap_d=60)),
    dict(id="mortgage_rate", name="Greece new mortgage lending rate, %", geo="GR", unit="pct", frequency="M", category="rates",
         source="ecb", key="MIR/M.GR.B.A2C.A.R.A.2250.EUR.N", snapshot=dict(dead_band=0.10, staleness_cap_d=75)),
    dict(id="deposit_rate", name="Greece household term-deposit rate (new business, <=1y), %", geo="GR", unit="pct", frequency="M", category="rates",
         source="ecb", key="MIR/M.GR.B.L22.F.R.A.2250.EUR.N", snapshot=dict(dead_band=0.10, staleness_cap_d=75)),
    dict(id="eurusd", name="EUR/USD reference rate (ECB)", geo="U2", unit="usd_per_eur", frequency="D", category="fx",
         source="ecb", key="EXR/D.USD.EUR.SP00.A", snapshot=dict(dead_band=0.02, staleness_cap_d=7)),
    # --- Global (FRED, needs FRED_API_KEY)
    dict(id="us_fed_funds", name="US effective federal funds rate, %", geo="US", unit="pct", frequency="M", category="rates",
         source="fred", key="FEDFUNDS", snapshot=dict(dead_band=0.10, staleness_cap_d=45)),
    dict(id="us_10y", name="US 10y Treasury yield, %", geo="US", unit="pct", frequency="D", category="rates",
         source="fred", key="DGS10", snapshot=dict(dead_band=0.10, staleness_cap_d=7)),
    dict(id="vix", name="CBOE VIX volatility index", geo="US", unit="index", frequency="D", category="sentiment",
         source="fred", key="VIXCLS", snapshot=dict(dead_band=2.0, staleness_cap_d=7)),
    dict(id="brent", name="Brent crude oil, USD/barrel", geo="GLOBAL", unit="usd", frequency="D", category="commodities",
         source="fred", key="DCOILBRENTEU", snapshot=dict(dead_band=3.0, staleness_cap_d=14)),
    # --- Crypto-wide
    dict(id="crypto_fear_greed", name="Crypto Fear & Greed index (0-100)", geo="GLOBAL", unit="index", frequency="D", category="crypto",
         source="fear_greed", snapshot=dict(dead_band=10.0, staleness_cap_d=3)),
    dict(id="defi_tvl", name="Total DeFi value locked, USD", geo="GLOBAL", unit="usd", frequency="D", category="crypto",
         source="defillama", snapshot=dict(dead_band_rel=0.05, staleness_cap_d=3)),
]

INDICATORS_BY_ID = {i["id"]: i for i in INDICATORS}
