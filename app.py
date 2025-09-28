# Archivo: app.py | Versión: Final con Lógica de Días de la Semana
from flask import Flask, render_template, request
import pandas as pd
import json
import random
from datetime import datetime, timedelta, time
import pytz

app = Flask(__name__)

# --- Funciones de Ayuda (con nueva compañía) ---
def get_icon_for_compania(compania, transporte=None):
    compania_str = str(compania).lower()
    if 'emtusa' in compania_str or 'urbano' in compania_str: return '🚍'
    if 'damas' in compania_str: return '🚌'
    if 'renfe' in compania_str: return '🚆'
    # MODIFICADO: Devuelve un código especial para el logo de Consorcio
    if 'consorcio' in compania_str: return 'LOGO_CONSORCIO'
    if 'coche' in compania_str or 'particular' in compania_str: return '🚗'
    transporte_str = str(transporte).lower()
    if 'tren' in transporte_str: return '🚆'
    if 'bus' in transporte_str: return '🚌'
    return '➡️'

def format_timedelta(td):
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0: return f"{hours}h {minutes}min"
    return f"{minutes}min"

def clean_minutes_column(series):
    def to_minutes(val):
        if pd.isna(val): return 0
        if isinstance(val, (int, float)): return val
        if isinstance(val, str):
            try:
                parts = list(map(int, val.split(':')))
                if len(parts) >= 2: return parts[0] * 60 + parts[1]
            except: return 0
        if isinstance(val, time): return val.hour * 60 + val.minute
        return 0
    return series.apply(to_minutes)

# --- Carga de Datos ---
try:
    rutas_df_global = pd.read_excel("rutas.xlsx", engine="openpyxl")
    rutas_df_global.columns = rutas_df_global.columns.str.strip()
    if 'Compañía' in rutas_df_global.columns:
        rutas_df_global.rename(columns={'Compañía': 'Compania'}, inplace=True)
    
    for col in ['Duracion_Trayecto_Min', 'Frecuencia_Min']:
        if col in rutas_df_global.columns:
            rutas_df_global[col] = clean_minutes_column(rutas_df_global[col])
    if 'Precio' in rutas_df_global.columns:
        rutas_df_global['Precio'] = pd.to_numeric(rutas_df_global['Precio'], errors='coerce').fillna(0)

except Exception as e:
    print(f"ERROR CRÍTICO al cargar 'rutas.xlsx': {e}")
    rutas_df_global = pd.DataFrame()

try:
    with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
        frases = json.load(f)
except Exception:
    frases = ["El esfuerzo de hoy es el éxito de mañana."]

@app.route("/")
def index():
    lugares = []
    if not rutas_df_global.empty:
        lugares = sorted(pd.concat([rutas_df_global["Origen"], rutas_df_global["Destino"]]).dropna().unique())
    frase = random.choice(frases)
    return render_template("index.html", lugares=lugares, frase=frase, frases=frases)

@app.route("/buscar", methods=["POST"])
def buscar():
    form_data = request.form.to_dict()
    origen = form_data.get("origen")
    destino = form_data.get("destino")
    
    # --- LÓGICA DE FILTRADO POR DÍA DE LA SEMANA ---
    tz = pytz.timezone('Europe/Madrid')
    now = datetime.now(tz)
    dia_seleccionado = form_data.get('dia_semana_selector', 'hoy')

    if dia_seleccionado != 'hoy':
        try:
            target_weekday = int(dia_seleccionado)
        except (ValueError, TypeError):
            target_weekday = now.weekday()
    else:
        target_weekday = now.weekday()

    dias_semana_map = {0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"}
    nombre_dia = dias_semana_map[target_weekday]

    rutas_hoy_df = rutas_df_global.copy()
    if 'Dias' in rutas_hoy_df.columns:
        rutas_hoy_df['Dias'] = rutas_hoy_df['Dias'].fillna('L-D').str.strip()
        is_weekday = target_weekday < 5
        is_saturday = target_weekday == 5
        is_sunday = target_weekday == 6
        mask = (rutas_hoy_df['Dias'] == 'L-D') | (is_weekday & (rutas_hoy_df['Dias'] == 'L-V')) | ((is_saturday or is_sunday) & (rutas_hoy_df['Dias'] == 'S-D')) | (is_saturday & (rutas_hoy_df['Dias'] == 'S')) | (is_sunday & (rutas_hoy_df['Dias'] == 'D'))
        rutas_hoy_df = rutas_hoy_df[mask]

    rutas_fijas_df = rutas_hoy_df[rutas_hoy_df['Tipo_Horario'] == 'Fijo'].copy()
    today_date = now.date()
    
    salida_times = pd.to_datetime(rutas_fijas_df['Salida'], format='%H:%M:%S', errors='coerce').dt.time
    llegada_times = pd.to_datetime(rutas_fijas_df['Llegada'], format='%H:%M:%S', errors='coerce').dt.time
    rutas_fijas_df['Salida_dt'] = salida_times.apply(lambda t: datetime.combine(today_date, t) if pd.notna(t) else pd.NaT)
    rutas_fijas_df['Llegada_dt'] = llegada_times.apply(lambda t: datetime.combine(today_date, t) if pd.notna(t) else pd.NaT)
    rutas_fijas_df.dropna(subset=['Salida_dt', 'Llegada_dt'], inplace=True)

    candidatos_plantilla = find_all_routes_intelligently(origen, destino, rutas_hoy_df)
    
    candidatos_expandidos = []
    for ruta_plantilla in candidatos_plantilla:
        if all(s['Tipo_Horario'] == 'Frecuencia' for s in ruta_plantilla):
            candidatos_expandidos.append(ruta_plantilla)
            continue
        indices_fijos = [i for i, seg in enumerate(ruta_plantilla) if seg['Tipo_Horario'] == 'Fijo']
        idx_ancla = indices_fijos[0]
        ancla_plantilla = ruta_plantilla[idx_ancla]
        mask = (rutas_fijas_df['Origen'] == ancla_plantilla['Origen']) & (rutas_fijas_df['Destino'] == ancla_plantilla['Destino'])
        if pd.notna(ancla_plantilla.get('Compania')): mask &= (rutas_fijas_df['Compania'] == ancla_plantilla['Compania'])
        if pd.notna(ancla_plantilla.get('Transporte')): mask &= (rutas_fijas_df['Transporte'] == ancla_plantilla['Transporte'])
        posibles_anclas = rutas_fijas_df[mask]
        for _, ancla_real in posibles_anclas.iterrows():
            nueva_ruta = ruta_plantilla[:]; nueva_ruta[idx_ancla] = ancla_real
            candidatos_expandidos.append(nueva_ruta)
    
    resultados_procesados = []
    for ruta in candidatos_expandidos:
        is_desde_ahora = form_data.get('desde_ahora') and dia_seleccionado == 'hoy'
        resultado = calculate_route_times(ruta, is_desde_ahora)
        if resultado: resultados_procesados.append(resultado)

    if form_data.get('desde_ahora') and dia_seleccionado == 'hoy':
        ahora = datetime.now(tz)
        resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] == 'Flexible' or r['segmentos'][0]['Salida_dt'].replace(tzinfo=None) >= ahora.replace(tzinfo=None)]

    def route_has_main_train(route): return any('renfe' in str(s.get('Compania', '')).lower() or 'tren' in str(s.get('Transporte', '')).lower() for s in route['segmentos'])
    def route_has_main_bus(route): return any('damas' in str(s.get('Compania', '')).lower() or 'bus' in str(s.get('Transporte', '')).lower() for s in route['segmentos'])
    def route_is_valid(route):
        st, sb = form_data.get('solo_tren'), form_data.get('solo_bus')
        if not st and not sb: return True
        tt, tb = route_has_main_train(route), route_has_main_bus(route)
        if not tt and not tb: return True
        if st and tt: return True
        if sb and tb: return True
        return False
    resultados_procesados = [r for r in resultados_procesados if route_is_valid(r)]

    lugares_a_evitar = []
    if form_data.get('evitar_sj'): lugares_a_evitar.append('Sta. Justa')
    if form_data.get('evitar_pa'): lugares_a_evitar.append('Plz. Armas')
    if lugares_a_evitar:
        resultados_procesados = [r for r in resultados_procesados if not any(s['Destino'] in lugares_a_evitar for s in r['segmentos'][:-1])]

    if form_data.get('salir_despues_check'):
        try:
            hl = time(int(form_data.get('salir_despues_hora')), int(form_data.get('salir_despues_minuto')))
            resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] == 'Flexible' or r['segmentos'][0]['Salida_dt'].time() >= hl]
        except: pass 
    if form_data.get('llegar_antes_check'):
        try:
            hl = time(int(form_data.get('llegar_antes_hora')), int(form_data.get('llegar_antes_minuto')))
            resultados_procesados = [r for r in resultados_procesados if r['hora_llegada_final'] != 'Flexible' and r['llegada_final_dt_obj'].time() < hl]
        except: pass
            
    resultados_unicos = {r['duracion_total_str'] + r['segmentos'][0]['Salida_str']: r for r in resultados_procesados}.values()
    if resultados_unicos:
        resultados_procesados = sorted(list(resultados_unicos), key=lambda x: x['llegada_final_dt_obj'])

    return render_template("resultado.html", origen=origen, destino=destino, resultados=resultados_procesados, filtros=form_data, dia_semana=nombre_dia)


def find_all_routes_intelligently(origen, destino, df):
    rutas, indices_unicos = [], set()
    for i, r in df[(df['Origen'] == origen) & (df['Destino'] == destino)].iterrows():
        if (i,) not in indices_unicos: rutas.append([r]); indices_unicos.add((i,))
    for i1, t1 in df[df['Origen'] == origen].iterrows():
        for i2, t2 in df[(df['Origen'] == t1['Destino']) & (df['Destino'] == destino)].iterrows():
            if (i1, i2) not in indices_unicos: rutas.append([t1, t2]); indices_unicos.add((i1, i2))
    if not rutas:
        for i1, t1 in df[df['Origen'] == origen].iterrows():
            for i2, t2 in df[df['Origen'] == t1['Destino']].iterrows():
                if t2['Destino'] in [origen, destino]: continue
                for i3, t3 in df[(df['Origen'] == t2['Destino']) & (df['Destino'] == destino)].iterrows():
                    if (i1, i2, i3) not in indices_unicos: rutas.append([t1, t2, t3]); indices_unicos.add((i1, i2, i3))
    return rutas

def calculate_route_times(ruta_series_list, desde_ahora_check):
    try:
        segmentos = [s.copy() for s in ruta_series_list]
        TIEMPO_TRANSBORDO = timedelta(minutes=10)
        
        if len(segmentos) == 1 and segmentos[0]['Tipo_Horario'] == 'Frecuencia':
            seg, duracion = segmentos[0], timedelta(minutes=segmentos[0]['Duracion_Trayecto_Min'])
            seg_dict = seg.to_dict()
            seg_dict.update({'icono': get_icon_for_compania(seg.get('Compania')), 'Salida_str': "A tu aire", 'Llegada_str': "", 'Duracion_Tramo_Min': seg['Duracion_Trayecto_Min'], 'Salida_dt': datetime.now(pytz.timezone('Europe/Madrid'))})
            return {"segmentos": [seg_dict], "precio_total": seg.get('Precio', 0), "llegada_final_dt_obj": datetime.min, "hora_llegada_final": "Flexible", "duracion_total_str": format_timedelta(duracion)}

        anchor_index = next((i for i, s in enumerate(segmentos) if 'Salida_dt' in s and pd.notna(s['Salida_dt'])), -1)
        
        if anchor_index != -1:
            llegada_siguiente_dt = segmentos[anchor_index]['Salida_dt']
            for i in range(anchor_index - 1, -1, -1):
                dur = timedelta(minutes=segmentos[i]['Duracion_Trayecto_Min'])
                segmentos[i]['Llegada_dt'] = llegada_siguiente_dt - TIEMPO_TRANSBORDO
                segmentos[i]['Salida_dt'] = segmentos[i]['Llegada_dt'] - dur
                llegada_siguiente_dt = segmentos[i]['Salida_dt']
            llegada_anterior_dt = segmentos[anchor_index]['Llegada_dt']
            for i in range(anchor_index + 1, len(segmentos)):
                dur = timedelta(minutes=segmentos[i]['Duracion_Trayecto_Min'])
                segmentos[i]['Salida_dt'] = llegada_anterior_dt + TIEMPO_TRANSBORDO
                segmentos[i]['Llegada_dt'] = segmentos[i]['Salida_dt'] + dur
                llegada_anterior_dt = segmentos[i]['Llegada_dt']
        else: # Ruta solo de frecuencia
            start_time = datetime.now(pytz.timezone('Europe/Madrid')) if desde_ahora_check else datetime.combine(datetime.today(), time(7,0))
            llegada_anterior_dt = None
            for i, seg in enumerate(segmentos):
                dur = timedelta(minutes=seg['Duracion_Trayecto_Min'])
                seg['Salida_dt'] = start_time if i == 0 else llegada_anterior_dt + TIEMPO_TRANSBORDO
                seg['Llegada_dt'] = seg['Salida_dt'] + dur
                llegada_anterior_dt = seg['Llegada_dt']
        
        primera_salida_dt = segmentos[0]['Salida_dt']
        segmentos_formateados = []
        for seg in segmentos:
            seg_dict = seg.to_dict()
            seg_dict.update({'icono': get_icon_for_compania(seg.get('Compania')), 'Salida_str': seg['Salida_dt'].strftime('%H:%M'), 'Llegada_str': seg['Llegada_dt'].strftime('%H:%M'), 'Duracion_Tramo_Min': (seg['Llegada_dt'] - seg['Salida_dt']).total_seconds() / 60})
            segmentos_formateados.append(seg_dict)
        segmentos_formateados[0]['Salida_dt'] = primera_salida_dt

        return {
            "segmentos": segmentos_formateados,
            "precio_total": sum(s.get('Precio', 0) for s in ruta_series_list),
            "llegada_final_dt_obj": segmentos[-1]['Llegada_dt'],
            "hora_llegada_final": segmentos[-1]['Llegada_dt'].time(),
            "duracion_total_str": format_timedelta(segmentos[-1]['Llegada_dt'] - segmentos[0]['Salida_dt'])
        }
    except Exception as e:
        return None

if __name__ == "__main__":
    app.run(debug=True)

