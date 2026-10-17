import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px
import os
from datetime import datetime

# Configuration de la page Streamlit
st.set_page_config(
    page_title="Suivi PEA",
    page_icon="📈",
    layout="wide"
)

TRANSACTIONS_FILE = "transactions.csv"
SECTEURS_FILE = "secteurs.csv"

# Initialisation du fichier de transactions s'il n'existe pas
if not os.path.exists(TRANSACTIONS_FILE):
    df_init = pd.DataFrame(columns=["Date", "ISIN", "Type", "Quantite", "Prix"])
    df_init.to_csv(TRANSACTIONS_FILE, index=False)

# Initialisation du fichier de secteurs personnalisés
if not os.path.exists(SECTEURS_FILE):
    df_sec_init = pd.DataFrame(columns=["ISIN", "Secteur"])
    df_sec_init.to_csv(SECTEURS_FILE, index=False)

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
    """Récupère les cours et les fondamentaux depuis yfinance via ISIN"""
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
                "SecteurAPI": info.get('sector', 'Inconnu'),
                "PER": info.get('trailingPE', np.nan),
                "CA": info.get('totalRevenue', np.nan),
                "MarketCap": info.get('marketCap', np.nan),
                "Benefice": info.get('netIncomeToCommon', np.nan),
                "Nom": info.get('shortName', isin)
            }
        except Exception:
            data[isin] = {
                "PrixActuel": 0,
                "SecteurAPI": "Inconnu",
                "PER": np.nan,
                "CA": np.nan,
                "MarketCap": np.nan,
                "Benefice": np.nan,
                "Nom": isin
            }
    return data

# --- HEADER & TITRE ---
st.title("📊 Tableau de bord PEA")
st.markdown("Suivi automatisé et analyse de votre portefeuille.")

# --- CHARGEMENT DES DONNÉES ---
df_trans = pd.read_csv(TRANSACTIONS_FILE)
df_secteurs_custom = pd.read_csv(SECTEURS_FILE)
custom_secteurs_dict = dict(zip(df_secteurs_custom['ISIN'], df_secteurs_custom['Secteur'])) if not df_secteurs_custom.empty else {}

# --- GESTION DES TRANSACTIONS & SECTEURS (MODE ADMIN) ---
with st.expander("🔐 Gestion / Ajout de transactions & Secteurs (Mode Admin)"):
    try:
        admin_password = st.secrets["ADMIN_PASSWORD"]
    except Exception:
        admin_password = "admin123"
    
    pwd_input = st.text_input("Mot de passe pour déverrouiller la gestion", type="password")
    
    if pwd_input == admin_password:
        st.success("Accès autorisé")
        
        tab1, tab2 = st.tabs(["➕ Transaction", "🏷️ Personnaliser un Secteur"])
        
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

        with tab2:
            st.markdown("Si le secteur renvoyé automatiquement ne vous convient pas, modifiez-le ici :")
            if not df_trans.empty:
                isins_existants = df_trans['ISIN'].unique().tolist()
                with st.form("form_secteur"):
                    selected_isin = st.selectbox("Sélectionner l'ISIN", isins_existants)
                    current_custom_sec = custom_secteurs_dict.get(selected_isin, "")
                    new_secteur = st.text_input("Nouveau Secteur", value=current_custom_sec)
                    
                    sub_sec = st.form_submit_button("Enregistrer le secteur")
                    if sub_sec and new_secteur:
                        df_secteurs_custom = df_secteurs_custom[df_secteurs_custom['ISIN'] != selected_isin]
                        new_sec_row = pd.DataFrame([[selected_isin, new_secteur.strip()]], columns=["ISIN", "Secteur"])
                        df_secteurs_custom = pd.concat([df_secteurs_custom, new_sec_row], ignore_index=True)
                        df_secteurs_custom.to_csv(SECTEURS_FILE, index=False)
                        st.success(f"Secteur mis à jour pour {selected_isin} !")
                        st.rerun()
            else:
                st.info("Ajoutez d'abord des transactions pour personnaliser leurs secteurs.")
                
    elif pwd_input != "":
        st.error("Mot de passe incorrect")

# --- CALCUL DU PORTEFEUILLE ---
if df_trans.empty:
    st.info("Aucune transaction enregistrée. Déverrouillez le mode Admin ci-dessus pour ajouter des transactions.")
else:
    df_calc = df_trans.copy()
    df_calc['QteEff'] = np.where(df_calc['Type'] == 'ACHAT', df_calc['Quantite'], -df_calc['Quantite'])
    df_calc['Investissement'] = np.where(df_calc['Type'] == 'ACHAT', df_calc['Quantite'] * df_calc['Prix'], -df_calc['Quantite'] * df_calc['Prix'])
    
    portfolio = df_calc.groupby('ISIN').agg({
        'QteEff': 'sum',
        'Investissement': 'sum'
    }).reset_index()
    
    portfolio = portfolio[portfolio['QteEff'] > 0]
    
    if portfolio.empty:
        st.warning("Aucune position active dans le portefeuille.")
    else:
        isins_list = portfolio['ISIN'].tolist()
        market_data = fetch_stock_data_by_isin(isins_list)
        
        portfolio['PrixActuel'] = portfolio['ISIN'].map(lambda x: market_data[x]['PrixActuel'])
        portfolio['Nom'] = portfolio['ISIN'].map(lambda x: market_data[x]['Nom'])
        
        # Secteur : soit le secteur personnalisé saisi par l'utilisateur, soit celui venant de l'API
        portfolio['Secteur'] = portfolio['ISIN'].map(lambda x: custom_secteurs_dict.get(x, market_data[x]['SecteurAPI']))
        
        portfolio['PER'] = portfolio['ISIN'].map(lambda x: market_data[x]['PER'])
        portfolio['CA_Raw'] = portfolio['ISIN'].map(lambda x: market_data[x]['CA'])
        portfolio['MarketCap_Raw'] = portfolio['ISIN'].map(lambda x: market_data[x]['MarketCap'])
        
        portfolio['CA'] = portfolio['CA_Raw'].apply(format_large_number)
        portfolio['Valorisation'] = portfolio['MarketCap_Raw'].apply(format_large_number)
        
        portfolio['ValeurActuelle'] = portfolio['QteEff'] * portfolio['PrixActuel']
        portfolio['PrixRevientMoyen'] = portfolio['Investissement'] / portfolio['QteEff']
        portfolio['PlusMoinsValue'] = portfolio['ValeurActuelle'] - portfolio['Investissement']
        portfolio['PerformancePct'] = (portfolio['PlusMoinsValue'] / portfolio['Investissement']) * 100

        # --- INDICATEURS CLÉS (KPIs) ---
        valeur_totale = portfolio['ValeurActuelle'].sum()
        investissement_total = portfolio['Investissement'].sum()
        plus_value_totale = valeur_totale - investissement_total
        perf_globale_pct = (plus_value_totale / investissement_total) * 100 if investissement_total > 0 else 0

        st.markdown("---")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("💰 Valeur Totale", f"{valeur_totale:,.2f} €")
        c2.metric("📈 Investissement Total", f"{investissement_total:,.2f} €")
        c3.metric("📊 Plus-Value Globale", f"{plus_value_totale:,.2f} €", f"{perf_globale_pct:.2f}%")
        c4.metric("📁 Lignes Actives", len(portfolio))

        st.markdown("---")
        st.subheader("Détail des positions")
        
        # Affichage du tableau nettoyé avec CA et Valorisation (Market Cap)
        df_display = portfolio[[
            'ISIN', 'Nom', 'QteEff', 'PrixRevientMoyen', 'PrixActuel', 
            'ValeurActuelle', 'PlusMoinsValue', 'PerformancePct', 
            'Secteur', 'PER', 'CA', 'Valorisation'
        ]].copy()
        
        df_display.columns = [
            'ISIN', 'Nom', 'Quantité', 'PRM (€)', 'Cours Actuel (€)', 
            'Valeur Actuelle (€)', '+/- Value (€)', 'Perf (%)', 
            'Secteur', 'PER', 'CA (Chiffre d\'Affaires)', 'Valorisation (Market Cap)'
        ]
        
        st.dataframe(df_display, use_container_width=True)

        # --- GRAPHIQUES DE RÉPARTITION ET PERFORMANCE ---
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