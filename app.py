import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px
import os
import json
from datetime import datetime

# Configuration de la page Streamlit
st.set_page_config(
    page_title="Suivi PEA",
    page_icon="📈",
    layout="wide"
)

TRANSACTIONS_FILE = "transactions.csv"
SECTEURS_FILE = "secteurs.csv"
CONFIG_FILE = "config.json"

# --- INITIALISATION DES FICHIERS ---
if not os.path.exists(TRANSACTIONS_FILE):
    df_init = pd.DataFrame(columns=["Date", "ISIN", "Type", "Quantite", "Prix"])
    df_init.to_csv(TRANSACTIONS_FILE, index=False)

if not os.path.exists(SECTEURS_FILE):
    df_sec_init = pd.DataFrame(columns=["ISIN", "Secteur"])
    df_sec_init.to_csv(SECTEURS_FILE, index=False)

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"pv_realisee_historique": 200.0}, f)

def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(config_data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f, indent=4)

def format_large_number(num):
    """Formatage lisible pour le CA et la Capitalisation Boursière"""
    if pd.isna(num) or num is None or num == 0:
        return "N/A"
    if abs(num) >= 1e12:
        return f"{num / 1e12:.2f}T €"
    elif abs(num) >= 1e9:
        return f"{num / 1e9:.2f}B €"
    elif abs(num) >= 1e6:
        return f"{num / 1e6:.2f}M €"
    else:
        return f"{num:,.0f} €"

@st.cache_data(ttl=3600)
def get_ticker_from_isin(isin):
    """Convertit un ISIN en Ticker Yahoo Finance"""
    isin = isin.strip().upper()
    try:
        search_result = yf.Search(isin, max_results=1).quotes
        if search_result and len(search_result) > 0:
            return search_result[0]['symbol']
    except Exception:
        pass
    return isin

@st.cache_data(ttl=3600)
def fetch_stock_data_by_isin(isins):
    """Récupère les cours et fondamentaux via yfinance"""
    data = {}
    for isin in isins:
        ticker_symbol = get_ticker_from_isin(isin)
        try:
            stock = yf.Ticker(ticker_symbol)
            info = stock.info
            hist = stock.history(period="1d")
            current_price = hist['Close'].iloc[-1] if not hist.empty else info.get('regularMarketPrice', 0)
            
            data[isin] = {
                "PrixActuel": current_price,
                "PER": info.get('trailingPE', np.nan),
                "CA": info.get('totalRevenue', np.nan),
                "MarketCap": info.get('marketCap', np.nan),
                "Nom": info.get('shortName', isin)
            }
        except Exception:
            data[isin] = {
                "PrixActuel": 0,
                "PER": np.nan,
                "CA": np.nan,
                "MarketCap": np.nan,
                "Nom": isin
            }
    return data

# --- HEADER & TITRE ---
st.title("📊 Tableau de bord PEA")
st.markdown("Suivi automatisé et analyse de votre portefeuille.")

# --- CHARGEMENT DES DONNÉES ---
df_trans = pd.read_csv(TRANSACTIONS_FILE)
df_secteurs = pd.read_csv(SECTEURS_FILE)
custom_secteurs_dict = dict(zip(df_secteurs['ISIN'], df_secteurs['Secteur'])) if not df_secteurs.empty else {}
config = load_config()

# --- CALCUL PRM PAR ISIN (Pour ajuster PV lors d'une vente) ---
def get_prm_dict(df):
    prm_dict = {}
    if df.empty:
        return prm_dict
    for isin, group in df.groupby('ISIN'):
        qte = 0
        total_cost = 0
        for _, row in group.iterrows():
            if row['Type'] == 'ACHAT':
                qte += row['Quantite']
                total_cost += row['Quantite'] * row['Prix']
            elif row['Type'] == 'VENTE':
                prm = total_cost / qte if qte > 0 else 0
                qte -= row['Quantite']
                total_cost -= row['Quantite'] * prm
        prm_dict[isin] = total_cost / qte if qte > 0 else 0
    return prm_dict

# --- GESTION DES TRANSACTIONS & CONFIG (MODE ADMIN) ---
with st.expander("🔐 Mode Admin : Transactions, Plus-Values & Secteurs"):
    try:
        admin_password = st.secrets["ADMIN_PASSWORD"]
    except Exception:
        admin_password = "admin123"
    
    pwd_input = st.text_input("Mot de passe pour déverrouiller la gestion", type="password")
    
    if pwd_input == admin_password:
        st.success("Accès autorisé")
        
        tab1, tab2, tab3 = st.tabs(["➕ Nouvelle Transaction", "💰 Plus-Values Réalisées", "🏷️ Secteurs des Actions"])
        
        # TAB 1 : TRANSACTIONS
        with tab1:
            with st.form("form_transaction"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    date_trans = st.date_input("Date", datetime.today())
                    isin_input = st.text_input("Code ISIN (ex: FR0000121014, US0378331005)").upper().strip()
                with col2:
                    type_trans = st.selectbox("Type", ["ACHAT", "VENTE"])
                    quantite = st.number_input("Quantité", min_value=0.0001, format="%.4f", value=1.0)
                with col3:
                    prix_trans = st.number_input("Prix unitaire (€)", min_value=0.0, format="%.2f", value=100.0)
                
                submitted = st.form_submit_button("Enregistrer la transaction")
                if submitted and isin_input:
                    # Si c'est une VENTE, calculer la PV réalisée et mettre à jour le solde
                    if type_trans == "VENTE":
                        prm_map = get_prm_dict(df_trans)
                        prm_vente = prm_map.get(isin_input, prix_trans)
                        pv_vente = (prix_trans - prm_vente) * quantite
                        config["pv_realisee_historique"] += pv_vente
                        save_config(config)
                        st.info(f"Plus-value réalisée sur cette vente : {pv_vente:,.2f} € (ajoutée au solde global)")
                    
                    new_row = pd.DataFrame([[date_trans, isin_input, type_trans, quantite, prix_trans]], 
                                             columns=["Date", "ISIN", "Type", "Quantite", "Prix"])
                    df_trans = pd.concat([df_trans, new_row], ignore_index=True)
                    df_trans.to_csv(TRANSACTIONS_FILE, index=False)
                    st.success("Transaction enregistrée avec succès !")
                    st.rerun()

            if not df_trans.empty:
                st.subheader("Historique des transactions")
                st.dataframe(df_trans, use_container_width=True)
                if st.button("Supprimer la dernière transaction"):
                    df_trans = df_trans.iloc[:-1]
                    df_trans.to_csv(TRANSACTIONS_FILE, index=False)
                    st.rerun()

        # TAB 2 : PLUS-VALUES RÉALISÉES / RÉINVESTIES
        with tab2:
            st.markdown("### Montant des Plus-Values Réalisées et Réinvesties")
            st.write("Ce montant est déduit de vos achats pour calculer votre **Investissement Réel (Capital Apporté)**.")
            with st.form("form_pv"):
                current_pv = float(config.get("pv_realisee_historique", 200.0))
                new_pv = st.number_input("Plus-value réalisée globale (€)", value=current_pv, format="%.2f")
                sub_pv = st.form_submit_button("Mettre à jour le solde des Plus-Values")
                if sub_pv:
                    config["pv_realisee_historique"] = new_pv
                    save_config(config)
                    st.success("Solde de plus-value mis à jour avec succès !")
                    st.rerun()

        # TAB 3 : SECTEURS
        with tab3:
            st.markdown("### Renseigner les Secteurs de vos Actions")
            active_isins = df_trans['ISIN'].unique().tolist() if not df_trans.empty else []
            
            if active_isins:
                with st.form("form_secteurs_multi"):
                    updated_secteurs = {}
                    for isin in active_isins:
                        val_actuelle = custom_secteurs_dict.get(isin, "Autre")
                        updated_secteurs[isin] = st.text_input(f"Secteur pour {isin}", value=val_actuelle)
                    
                    sub_sec_multi = st.form_submit_button("Enregistrer tous les secteurs")
                    if sub_sec_multi:
                        df_sec_new = pd.DataFrame(list(updated_secteurs.items()), columns=["ISIN", "Secteur"])
                        df_sec_new.to_csv(SECTEURS_FILE, index=False)
                        st.success("Tous les secteurs ont été enregistrés !")
                        st.rerun()
            else:
                st.info("Ajoutez d'abord des transactions pour définir leurs secteurs.")
                
    elif pwd_input != "":
        st.error("Mot de passe incorrect")

# --- CALCUL DU PORTEFEUILLE ---
if df_trans.empty:
    st.info("Aucune transaction enregistrée. Déverrouillez le mode Admin ci-dessus pour ajouter des transactions.")
else:
    df_calc = df_trans.copy()
    df_calc['QteEff'] = np.where(df_calc['Type'] == 'ACHAT', df_calc['Quantite'], -df_calc['Quantite'])
    df_calc['InvestissementBrut'] = np.where(df_calc['Type'] == 'ACHAT', df_calc['Quantite'] * df_calc['Prix'], -df_calc['Quantite'] * df_calc['Prix'])
    
    portfolio = df_calc.groupby('ISIN').agg({
        'QteEff': 'sum',
        'InvestissementBrut': 'sum'
    }).reset_index()
    
    portfolio = portfolio[portfolio['QteEff'] > 0]
    
    if portfolio.empty:
        st.warning("Aucune position active dans le portefeuille.")
    else:
        isins_list = portfolio['ISIN'].tolist()
        market_data = fetch_stock_data_by_isin(isins_list)
        
        portfolio['PrixActuel'] = portfolio['ISIN'].map(lambda x: market_data[x]['PrixActuel'])
        portfolio['Nom'] = portfolio['ISIN'].map(lambda x: market_data[x]['Nom'])
        portfolio['Secteur'] = portfolio['ISIN'].map(lambda x: custom_secteurs_dict.get(x, "Inconnu"))
        
        portfolio['PER'] = portfolio['ISIN'].map(lambda x: market_data[x]['PER'])
        portfolio['CA_Raw'] = portfolio['ISIN'].map(lambda x: market_data[x]['CA'])
        portfolio['MarketCap_Raw'] = portfolio['ISIN'].map(lambda x: market_data[x]['MarketCap'])
        
        portfolio['CA'] = portfolio['CA_Raw'].apply(format_large_number)
        portfolio['Valorisation'] = portfolio['MarketCap_Raw'].apply(format_large_number)
        
        portfolio['ValeurActuelle'] = portfolio['QteEff'] * portfolio['PrixActuel']
        portfolio['PrixRevientMoyen'] = portfolio['InvestissementBrut'] / portfolio['QteEff']
        portfolio['PlusMoinsValue'] = portfolio['ValeurActuelle'] - portfolio['InvestissementBrut']
        portfolio['PerformancePct'] = (portfolio['PlusMoinsValue'] / portfolio['InvestissementBrut']) * 100

        # --- INDICATEURS CLÉS (KPIs) ---
        valeur_totale = portfolio['ValeurActuelle'].sum()
        achats_cumules = portfolio['InvestissementBrut'].sum()
        pv_realisee = config.get("pv_realisee_historique", 0.0)
        
        # Capital Réel Apporté (Achats - PV Réalisée déjà réinvestie)
        investissement_reel = max(0.0, achats_cumules - pv_realisee)
        
        # Plus Value Globale du PEA (Valeur Actuelle - Capital Réellement Apporté)
        plus_value_globale = valeur_totale - investissement_reel
        perf_globale_pct = (plus_value_globale / investissement_reel) * 100 if investissement_reel > 0 else 0

        st.markdown("---")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("💰 Valeur Totale", f"{valeur_totale:,.2f} €")
        c2.metric("💳 Apports Réels", f"{investissement_reel:,.2f} €", delta=f"-{pv_realisee:,.2f} € PV Réinvestie", delta_color="normal")
        c3.metric("📊 Plus-Value Globale", f"{plus_value_globale:,.2f} €", f"{perf_globale_pct:.2f}%")
        c4.metric("📁 Lignes Actives", len(portfolio))

        st.markdown("---")
        st.subheader("Détail des positions")
        
        df_display = portfolio[[
            'ISIN', 'Nom', 'QteEff', 'PrixRevientMoyen', 'PrixActuel', 
            'ValeurActuelle', 'PlusMoinsValue', 'PerformancePct', 
            'Secteur', 'PER', 'CA', 'Valorisation'
        ]].copy()
        
        df_display.columns = [
            'ISIN', 'Nom', 'Quantité', 'PRM (€)', 'Cours Actuel (€)', 
            'Valeur Actuelle (€)', '+/- Value (€)', 'Perf (%)', 
            'Secteur', 'PER', 'CA', 'Valorisation'
        ]
        
        st.dataframe(df_display, use_container_width=True)

        # --- GRAPHIQUES ---
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.subheader("Répartition Sectorielle")
            fig_secteur = px.pie(portfolio, values='ValeurActuelle', names='Secteur', hole=0.4)
            st.plotly_chart(fig_secteur, use_container_width=True)
            
        with col_g2:
            st.subheader("Performance par Ligne (%)")
            fig_perf = px.bar(
                portfolio, 
                x='Nom', 
                y='PerformancePct', 
                color='PerformancePct', 
                color_continuous_scale='RdYlGn',
                labels={'Nom': 'Action', 'PerformancePct': 'Performance (%)'}
            )
            st.plotly_chart(fig_perf, use_container_width=True)
