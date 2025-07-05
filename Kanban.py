# -*- coding: utf-8 -*-
"""
Created on Tue Jul  1 21:28:42 2025

@author: acer
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime
import os
import sqlite3
import hashlib
import plotly.express as px
import base64
from io import BytesIO

st.set_page_config(layout="wide")
st.title("🛠️ Gestión Actividades Kanban Soporte Electrónico")

# --- Database Configuration ---
DB_DIR = "kanban_db"
os.makedirs(DB_DIR, exist_ok=True)
DB_FILE = os.path.join(DB_DIR, "kanban.db")

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            date TEXT NOT NULL,
            priority TEXT NOT NULL,
            shift TEXT NOT NULL,
            status TEXT NOT NULL,
            completion_date TEXT,
            start_date TEXT,
            due_date TEXT,
            description TEXT,
            progress INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_collaborators (
            task_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            PRIMARY KEY (task_id, username),
            FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE,
            FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            action_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            comment_text TEXT,
            image_base64 TEXT,
            new_status TEXT,
            progress_value INTEGER
        )
    """)

    default_users = {
        "Admin Principal": {"password": "admin_password", "role": "Admin"}
    }
    for username, data in default_users.items():
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        if cursor.fetchone() is None:
            hashed_password = hashlib.sha256(data["password"].encode()).hexdigest()
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                         (username, hashed_password, data["role"]))

    conn.commit()
    conn.close()

init_db()

# --- User Authentication ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_role" not in st.session_state:
    st.session_state.current_role = None
if "username" not in st.session_state:
    st.session_state.username = None

def login(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed_password_input = hashlib.sha256(password.encode()).hexdigest()

    cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?",
                 (username, hashed_password_input))
    user = cursor.fetchone()
    conn.close()

    if user:
        st.session_state.logged_in = True
        st.session_state.current_role = user["role"]
        st.session_state.username = user["username"]
        st.success(f"¡Bienvenido, {st.session_state.username}!")
        st.rerun()
    else:
        st.error("Usuario o contraseña incorrectos.")

def logout():
    st.session_state.logged_in = False
    st.session_state.current_role = None
    st.session_state.username = None
    st.info("Has cerrado sesión.")
    st.rerun()

if not st.session_state.logged_in:
    st.sidebar.header("Inicio de Sesión")
    with st.sidebar.form("login_form"):
        username_input = st.text_input("Usuario")
        password_input = st.text_input("Contraseña", type="password")
        login_button = st.form_submit_button("Iniciar Sesión")
        if login_button:
            login(username_input, password_input)
    st.stop()

st.sidebar.header("Sesión Actual")
st.sidebar.write(f"Usuario: **{st.session_state.username}**")
st.sidebar.write(f"Rol: **{st.session_state.current_role}**")
if st.sidebar.button("Cerrar Sesión"):
    logout()

# --- Task Management Functions ---
def load_tasks_from_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tasks")
    tasks_raw = cursor.fetchall()

    kanban_data = {
        "Por hacer": [],
        "En proceso": [],
        "Hecho": []
    }
    all_tasks_list = []

    for task_row in tasks_raw:
        task_dict = dict(task_row)

        collaborators_cursor = conn.execute("SELECT username FROM task_collaborators WHERE task_id = ?", (task_dict['id'],))
        task_dict['responsible_list'] = [row['username'] for row in collaborators_cursor.fetchall()]
        task_dict['responsible'] = ", ".join(task_dict['responsible_list'])

        # Obtener TODAS las interacciones ordenadas por fecha (más antiguas primero)
        interactions_cursor = conn.execute(
            "SELECT comment_text, image_base64, username, timestamp FROM task_interactions WHERE task_id = ? ORDER BY timestamp ASC",
            (task_dict['id'],)
        )
        task_dict['interactions'] = [dict(interaction) for interaction in interactions_cursor.fetchall()]

        if 'id' not in task_dict:
            task_dict['id'] = None

        kanban_data[task_dict['status']].append(task_dict)
        all_tasks_list.append(task_dict)

    conn.close()
    st.session_state.kanban = kanban_data
    st.session_state.all_tasks_df = pd.DataFrame(all_tasks_list)

def add_task_to_db(task_data, initial_status, responsible_usernames):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO tasks (task, date, priority, shift, status, completion_date, start_date, due_date, description, progress) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_data["tarea"], task_data["fecha"],
             task_data["prioridad"], task_data["turno"], initial_status, None,
             task_data["fecha_inicial"], task_data["fecha_termino"], task_data["description"], 0)
        )
        task_id = cursor.lastrowid
        st.success("✅ Tarea agregada a la base de datos.")

        if responsible_usernames:
            for username in responsible_usernames:
                cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
                existing_user = cursor.fetchone()

                if existing_user is None:
                    default_collab_password = "colab_nueva_tarea"
                    hashed_default_password = hashlib.sha256(default_collab_password.encode()).hexdigest()
                    cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                                   (username, hashed_default_password, "Colaborador"))
                    st.info(f"Nuevo usuario colaborador '{username}' creado con contraseña por defecto: '{default_collab_password}'.")

                cursor.execute("INSERT INTO task_collaborators (task_id, username) VALUES (?, ?)",
                               (task_id, username))
            st.success(f"Asignados responsables a la tarea.")
        else:
            st.warning("No se asignaron responsables a esta tarea.")

        conn.commit()
    except Exception as e:
        st.error(f"Error al agregar tarea o asignar responsables: {e}")
    finally:
        conn.close()
    load_tasks_from_db()

def update_task_status_in_db(task_id, new_status, completion_date=None, progress=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = "UPDATE tasks SET status = ?"
        params = [new_status]
        if completion_date:
            query += ", completion_date = ?"
            params.append(completion_date)
        if progress is not None:
            query += ", progress = ?"
            params.append(progress)

        query += " WHERE id = ?"
        params.append(task_id)

        cursor.execute(query, tuple(params))
        conn.commit()
        st.success("✅ Estado de tarea actualizado en la base de datos.")
    except Exception as e:
        st.error(f"Error al actualizar tarea: {e}")
    finally:
        conn.close()
    load_tasks_from_db()

def add_task_interaction(task_id, username, action_type, comment_text=None, image_base64=None, new_status=None, progress_value=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO task_interactions (task_id, username, action_type, timestamp, comment_text, image_base64, new_status, progress_value) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, username, action_type, timestamp, comment_text, image_base64, new_status, progress_value)
        )
        conn.commit()
        st.success(f"Interacción '{action_type}' registrada.")
    except Exception as e:
        st.error(f"Error al registrar interacción: {e}")
    finally:
        conn.close()
    load_tasks_from_db()

def update_user_password_in_db(username, new_password):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        hashed_new_password = hashlib.sha256(new_password.encode()).hexdigest()
        cursor.execute(
            "UPDATE users SET password = ? WHERE username = ?",
            (hashed_new_password, username)
        )
        conn.commit()
        st.success(f"✅ Contraseña de '{username}' actualizada exitosamente.")
    except Exception as e:
        st.error(f"Error al actualizar la contraseña de '{username}': {e}")
    finally:
        conn.close()

def create_new_user_in_db(username, password, role):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            st.error(f"El usuario '{username}' ya existe.")
            return False

        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                       (username, hashed_password, role))
        conn.commit()
        st.success(f"Usuario '{username}' con rol '{role}' creado exitosamente.")
        return True
    except Exception as e:
        st.error(f"Error al crear el usuario '{username}': {e}")
        return False
    finally:
        conn.close()

def generate_excel_export():
    conn = get_db_connection()
    output = BytesIO()
    try:
        df_tasks = pd.read_sql_query("SELECT * FROM tasks", conn)
        df_collaborators = pd.read_sql_query("SELECT * FROM task_collaborators", conn)
        df_interactions = pd.read_sql_query("SELECT * FROM task_interactions", conn)

        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            if not df_tasks.empty:
                df_tasks.to_excel(writer, sheet_name='Tareas', index=False)
            if not df_collaborators.empty:
                df_collaborators.to_excel(writer, sheet_name='Colaboradores_Tareas', index=False)
            if not df_interactions.empty:
                df_interactions.to_excel(writer, sheet_name='Interacciones_Tareas', index=False)

        output.seek(0)
        st.success("Historial de la base de datos generado para descarga.")
        return output
    except Exception as e:
        st.error(f"Error al generar el archivo de historial: {e}")
        return None
    finally:
        conn.close()

def clear_task_data_from_db():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM task_collaborators")
        cursor.execute("DELETE FROM task_interactions")
        cursor.execute("DELETE FROM tasks")
        conn.commit()
        st.success("Tablas de tareas, colaboradores e interacciones vaciadas.")
    except Exception as e:
        st.error(f"Error al vaciar la base de datos: {e}")
    finally:
        conn.close()
    load_tasks_from_db()

# --- Formatear Tarea ---
def formatear_tarea_display(t):
    card_color = "#393E46"

    if t['status'] == 'Hecho':
        card_color = "#4CAF50"
    elif t['status'] in ['Por hacer', 'En proceso']:
        if t.get('due_date'):
            try:
                task_due_date = date.fromisoformat(t['due_date'])
                today = date.today()
                if task_due_date <= today:
                    card_color = "#F44336"
                elif task_due_date <= today + timedelta(days=3):
                    card_color = "#FFC107"
            except ValueError:
                pass

    description_html = f"<br><strong>📝 Descripción:</strong> {t['description']}" if t.get('description') else ""
    start_date_html = f"<br><strong>➡️ Inicio:</strong> {t['start_date']}" if t.get('start_date') else ""
    due_date_html = f"<br><strong>🔚 Término:</strong> {t['due_date']}" if t.get('due_date') else ""

    responsible_display = ", ".join(t.get('responsible_list', [])) or "Sin asignar"

    progress_html = f"""
    <div style="width: 100%; background-color: #ddd; border-radius: 5px; margin-top: 8px; overflow: hidden;">
        <div style="width: {t['progress']}%; background-color: #007bff; color: white; text-align: center; border-radius: 5px; padding: 2px 0;">
            {t['progress']}%
        </div>
    </div>
    """

    card_html = f"""
    <div style="background-color:{card_color}; color:white; padding: 10px; border-radius: 5px; margin-bottom: 10px;">
        <strong>🔧 Tarea:</strong> {t['task']}
        {description_html}
        <br><strong>👷 Responsables:</strong> {responsible_display}
        <br><strong>📅 Creada:</strong> {t['date']}
        {start_date_html}
        {due_date_html}
        <br><strong>🧭 Turno:</strong> {t['shift']}
        <br><strong>🔥 Prioridad:</strong> {t['priority']}
        {progress_html}
    </div>
    """

    return {
        'card_html': card_html,
        'interactions': t.get('interactions', [])
    }

# --- Tab Creation ---
admin_roles = ["Admin", "Supervisor", "Coordinador"]
if st.session_state.current_role in admin_roles:
    tab1, tab2, tab3, tab4 = st.tabs(["➕ Agregar Tarea", "📋 Tablero Kanban", "📊 Estadísticas", "⚙️ Gestión Usuarios"])
else:
    tab2, = st.tabs(["📋 Tablero Kanban"])

# --- Tab 1: Add Task ---
if st.session_state.current_role in admin_roles:
    with tab1:
        st.header("➕ Agregar Nueva Tarea")
        st.markdown("---")

        with st.form("agregar_tarea"):
            st.subheader("Detalles de la Tarea")
            tarea = st.text_input("Nombre de la Tarea")
            description = st.text_area("Descripción de la Tarea (Opcional)")

            conn_users = get_db_connection()
            collab_users_raw = conn_users.execute("SELECT username FROM users WHERE role != 'Admin'").fetchall()
            conn_users.close()
            all_collab_usernames = [row['username'] for row in collab_users_raw]

            responsables_existentes_seleccionados = st.multiselect(
                "Seleccionar Responsables Existentes:",
                options=all_collab_usernames,
                default=[],
                key="responsables_existentes_multiselect"
            )

            nuevo_responsable_input = st.text_input(
                "Añadir Nuevo Colaborador (escribe y presiona Enter):",
                key="nuevo_responsable_text_input"
            )

            responsables_finales = list(responsables_existentes_seleccionados)
            if nuevo_responsable_input and nuevo_responsable_input.strip() not in responsables_finales:
                responsables_finales.append(nuevo_responsable_input.strip())

            fecha = st.date_input("Fecha de Creación", date.today())
            fecha_inicial = st.date_input("Fecha Inicial (Opcional)", value=None, key="fecha_inicial_input")
            fecha_termino = st.date_input("Fecha Término (Opcional)", value=None, key="fecha_termino_input")

            prioridad = st.selectbox("Prioridad", ["Alta", "Media", "Baja"])
            turno = st.selectbox("Turno", ["1er Turno", "2do Turno", "3er Turno"])
            destino = st.selectbox("Columna Inicial", ["Por hacer", "En proceso"])
            submit = st.form_submit_button("Crear Tarea")

            if submit and tarea and responsables_finales:
                nueva = {
                    "tarea": tarea,
                    "description": description,
                    "fecha": fecha.strftime("%Y-%m-%d"),
                    "prioridad": prioridad,
                    "turno": turno,
                    "fecha_inicial": fecha_inicial.strftime("%Y-%m-%d") if fecha_inicial else None,
                    "fecha_termino": fecha_termino.strftime("%Y-%m-%d") if fecha_termino else None
                }
                add_task_to_db(nueva, destino, responsables_finales)
                st.rerun()
            elif submit and (not tarea or not responsables_finales):
                st.error("Por favor, completa el nombre de la tarea y asigna al menos un responsable.")

# --- Tab 2: Kanban Board ---
with tab2:
    st.header("📋 Tablero Kanban")
    st.markdown("---")

    all_responsibles_flat = []
    for tareas_list in st.session_state.kanban.values():
        for t in tareas_list:
            all_responsibles_flat.extend(t.get('responsible_list', []))
    responsables_para_filtro = sorted(list(set(all_responsibles_flat)))

    default_filter_index = 0
    if st.session_state.current_role == "Colaborador" and st.session_state.username in responsables_para_filtro:
        try:
            default_filter_index = responsables_para_filtro.index(st.session_state.username) + 1
        except ValueError:
            pass

    usuario_actual = st.selectbox(
        "👤 Filtrar tareas por responsable:",
        ["(Todos)"] + responsables_para_filtro,
        index=default_filter_index,
        key="kanban_filter_user"
    )

    cols = st.columns(3)
    secciones = ["Por hacer", "En proceso", "Hecho"]

    for col, estado in zip(cols, secciones):
        with col:
            st.markdown(f"### {estado}")
            tareas = st.session_state.kanban[estado]

            visibles = [
                t for t in tareas
                if usuario_actual == "(Todos)" or usuario_actual in t.get("responsible_list", [])
            ]

            if visibles:
                for i, task in enumerate(visibles):
                    task_display = formatear_tarea_display(task)

                    st.markdown(task_display['card_html'], unsafe_allow_html=True)

                    if task_display['interactions']:
                        with st.expander(f"📝 Historial ({len(task_display['interactions'])})", expanded=False):
                            for interaction in task_display['interactions']:
                                if interaction['comment_text']:
                                    st.caption(f"💬 {interaction['username']} - {interaction['timestamp']}")
                                    st.info(interaction['comment_text'])

                                if interaction['image_base64']:
                                    st.caption(f"📸 Evidencia adjunta")
                                    try:
                                        image_data = base64.b64decode(interaction['image_base64'])
                                        st.image(image_data, use_column_width=True)
                                    except Exception as e:
                                        st.error("Error al cargar imagen")

                                st.markdown("---")  # Separador entre interacciones

                    if estado in ['Por hacer', 'En proceso']:
                        if st.session_state.current_role in admin_roles or st.session_state.username in task.get("responsible_list", []):
                            with st.expander(f"✏️ Actualizar tarea: {task['task']}", expanded=False):
                                comment_key = f"comment-{task['id']}-{i}"
                                uploaded_file_key = f"upload-{task['id']}-{i}"
                                progress_slider_key = f"progress_slider-{task['id']}-{i}"

                                current_progress = task.get('progress', 0)
                                new_progress = st.slider("Porcentaje de Avance:", 0, 100, current_progress, 10, key=progress_slider_key)

                                comment_text = st.text_area("Comentario:", key=comment_key)
                                uploaded_file = st.file_uploader("Subir Evidencia (PNG/JPG):", type=["png", "jpg", "jpeg"], key=uploaded_file_key)

                                col_buttons_interaction = st.columns(2)

                                with col_buttons_interaction[0]:
                                    if st.button(f"Actualizar Avance y Comentario", key=f"submit_progress_comment-{task['id']}-{i}"):
                                        image_base64 = None
                                        if uploaded_file is not None:
                                            bytes_data = uploaded_file.getvalue()
                                            image_base64 = base64.b64encode(bytes_data).decode('utf-8')
                                            st.success("Imagen cargada y codificada.")

                                        update_task_status_in_db(task['id'], task['status'], progress=new_progress)

                                        add_task_interaction(
                                            task_id=task['id'],
                                            username=st.session_state.username,
                                            action_type='progress_update',
                                            comment_text=comment_text,
                                            image_base64=image_base64,
                                            progress_value=new_progress
                                        )
                                        st.rerun()

                                with col_buttons_interaction[1]:
                                    if st.button(f"Marcar como Hecha (100% Avance)", key=f"submit_done-{task['id']}-{i}"):
                                        image_base64 = None
                                        if uploaded_file is not None:
                                            bytes_data = uploaded_file.getvalue()
                                            image_base64 = base64.b64encode(bytes_data).decode('utf-8')
                                            st.success("Imagen cargada y codificada.")

                                        update_task_status_in_db(task['id'], "Hecho", date.today().strftime("%Y-%m-%d"), progress=100)

                                        add_task_interaction(
                                            task_id=task['id'],
                                            username=st.session_state.username,
                                            action_type='status_change_to_done',
                                            comment_text=comment_text,
                                            image_base64=image_base64,
                                            new_status="Hecho",
                                            progress_value=100
                                        )
                                        st.rerun()
            else:
                st.info("No hay tareas en esta sección.")

# --- Tab 3: Statistics ---
if st.session_state.current_role in admin_roles:
    with tab3:
        st.header("📊 Estadísticas del Kanban")
        st.markdown("---")

        if not st.session_state.all_tasks_df.empty:
            df_tasks = st.session_state.all_tasks_df.copy()

            st.subheader("Distribución de Tareas por Estado")
            status_counts = df_tasks['status'].value_counts().reset_index()
            status_counts.columns = ['Estado', 'Número de Tareas']
            fig1 = px.bar(status_counts, x='Estado', y='Número de Tareas', color='Estado',
                          title='Tareas por Estado',
                          labels={'Estado':'Estado de la Tarea', 'Número de Tareas':'Cantidad'},
                          color_discrete_map={"Por hacer": "#393E46", "En proceso": "#FFC107", "Hecho": "#4CAF50"})
            st.plotly_chart(fig1, use_container_width=True)

            st.subheader("Avance Total por Responsable y Estado")
            expanded_tasks_for_progress = []
            for index, row in df_tasks.iterrows():
                if 'responsible_list' in row and row['responsible_list']:
                    for resp in row['responsible_list']:
                        expanded_tasks_for_progress.append({
                            'Responsable': resp,
                            'Avance': row['progress'],
                            'Estado': row['status']
                        })

            if expanded_tasks_for_progress:
                df_progress = pd.DataFrame(expanded_tasks_for_progress)
                df_progress_agg = df_progress.groupby(['Responsable', 'Estado'])['Avance'].sum().reset_index()

                status_color_map = {
                    "Por hacer": "#393E46",
                    "En proceso": "#FFC107",
                    "Hecho": "#4CAF50"
                }

                fig_progress = px.bar(df_progress_agg,
                                      x='Responsable',
                                      y='Avance',
                                      color='Estado',
                                      title='Avance Total por Responsable y Estado',
                                      labels={'Avance':'Avance Acumulado (%)', 'Responsable':'Responsable'},
                                      color_discrete_map=status_color_map,
                                      barmode='stack')
                st.plotly_chart(fig_progress, use_container_width=True)
            else:
                st.info("No hay datos de avance para mostrar estadísticas por responsable.")

            st.subheader("Distribución de Tareas por Prioridad")
            priority_counts = df_tasks['priority'].value_counts().reset_index()
            priority_counts.columns = ['Prioridad', 'Cantidad']
            priority_order = ["Alta", "Media", "Baja"]
            priority_counts['Prioridad'] = pd.Categorical(priority_counts['Prioridad'], categories=priority_order, ordered=True)
            priority_counts = priority_counts.sort_values('Prioridad')

            fig3 = px.pie(priority_counts, values='Cantidad', names='Prioridad',
                          title='Tareas por Prioridad',
                          hole=0.3)
            st.plotly_chart(fig3, use_container_width=True)

            st.subheader("Estado de Actividades por Vencimiento")
            pending_tasks = df_tasks[df_tasks['status'].isin(['Por hacer', 'En proceso'])].copy()

            if not pending_tasks.empty:
                today = date.today()
                pending_tasks['due_date_obj'] = pending_tasks['due_date'].apply(
                    lambda x: date.fromisoformat(x) if pd.notna(x) else None
                )

                def categorize_due_date(row):
                    if row['due_date_obj'] is None:
                        return "Sin Fecha de Término"
                    elif row['due_date_obj'] <= today:
                        return "Vencida"
                    elif row['due_date_obj'] <= today + timedelta(days=7):
                        return "Por Vencer"
                    else:
                        return "A Tiempo"

                pending_tasks['Estado Vencimiento'] = pending_tasks.apply(categorize_due_date, axis=1)
                due_date_counts = pending_tasks['Estado Vencimiento'].value_counts().reset_index()
                due_date_counts.columns = ['Categoría', 'Número de Tareas']

                category_order = ["Vencida", "Por Vencer", "A Tiempo", "Sin Fecha de Término"]
                due_date_counts['Categoría'] = pd.Categorical(due_date_counts['Categoría'], categories=category_order, ordered=True)
                due_date_counts = due_date_counts.sort_values('Categoría')

                color_map = {
                    "Vencida": "#F44336",
                    "Por Vencer": "#FFC107",
                    "A Tiempo": "#4CAF50",
                    "Sin Fecha de Término": "#808080"
                }

                fig4 = px.bar(due_date_counts, x='Categoría', y='Número de Tareas', color='Categoría',
                              title='Actividades por Estado de Vencimiento',
                              labels={'Categoría':'Estado de Vencimiento', 'Número de Tareas':'Cantidad'},
                              color_discrete_map=color_map)
                st.plotly_chart(fig4, use_container_width=True)
            else:
                st.info("No hay tareas pendientes para analizar su vencimiento.")
        else:
            st.info("No hay datos de tareas para generar estadísticas.")

# --- Tab 4: User Management ---
if st.session_state.current_role in admin_roles:
    with tab4:
        st.header("⚙️ Gestión de Usuarios")
        st.markdown("---")

        conn = get_db_connection()
        all_users_raw = conn.execute("SELECT username, role FROM users").fetchall()
        conn.close()

        if all_users_raw:
            df_users = pd.DataFrame([dict(row) for row in all_users_raw])
            st.subheader("Lista de Usuarios Existentes")
            st.dataframe(df_users, use_container_width=True)

            if st.session_state.current_role == "Admin":
                st.markdown("---")
                st.subheader("Crear Nuevo Usuario")
                with st.form("create_new_user_form"):
                    new_username = st.text_input("Nombre de Usuario para el nuevo usuario:")
                    new_password = st.text_input("Contraseña para el nuevo usuario:", type="password")
                    confirm_new_password = st.text_input("Confirmar Contraseña:", type="password")
                    new_user_role = st.selectbox("Rol del nuevo usuario:", ["Admin", "Supervisor", "Coordinador", "Colaborador"])
                    create_user_button = st.form_submit_button("Crear Usuario")

                    if create_user_button:
                        if new_username and new_password and confirm_new_password:
                            if new_password == confirm_new_password:
                                if create_new_user_in_db(new_username, new_password, new_user_role):
                                    st.rerun()
                            else:
                                st.error("Las contraseñas no coinciden.")
                        else:
                            st.warning("Por favor, completa todos los campos para crear un nuevo usuario.")

            st.markdown("---")
            st.subheader("Restablecer Contraseña de Usuario")
            with st.form("reset_password_form"):
                users_list = df_users['username'].tolist()
                user_to_reset = st.selectbox("Seleccionar Usuario:", users_list)
                new_password = st.text_input("Nueva Contraseña:", type="password", key="reset_new_password")
                confirm_password = st.text_input("Confirmar Nueva Contraseña:", type="password", key="reset_confirm_password")
                reset_button = st.form_submit_button("Restablecer Contraseña")

                if reset_button:
                    if new_password and new_password == confirm_password:
                        update_user_password_in_db(user_to_reset, new_password)
                        st.rerun()
                    elif not new_password:
                        st.warning("Por favor, introduce una nueva contraseña.")
                    else:
                        st.error("Las contraseñas no coinciden.")
        else:
            st.info("No hay usuarios registrados en la base de datos.")

        st.markdown("---")
        st.subheader("Administración de la Base de Datos")
        st.warning("¡CUIDADO! Estas acciones son sensibles y pueden afectar los datos de la aplicación.")

        if st.button("Generar Historial para Descargar (Excel)", key="generate_excel_button"):
            excel_data_bytes = generate_excel_export()
            if excel_data_bytes:
                st.download_button(
                    label="Descargar Archivo Excel",
                    data=excel_data_bytes,
                    file_name=f"kanban_historial_{date.today().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_generated_excel"
                )
                st.info("Haz clic en el botón 'Descargar Archivo Excel' de arriba para guardar el historial.")

        st.markdown("---")
        st.warning("¡ADVERTENCIA! La siguiente acción eliminará **todos** los datos de tareas, colaboradores e interacciones.")
        confirm_clear = st.checkbox("Entiendo que esta acción es irreversible y vaciará las tareas y sus interacciones.", key="confirm_clear_checkbox")
        if confirm_clear:
            if st.button("Vaciar Base de Datos (Tareas, Comentarios, Evidencias)", key="clear_db_button"):
                clear_task_data_from_db()
                st.rerun()

# --- Data Export to Excel ---
excel_data = []
for estado, tareas in st.session_state.kanban.items():
    for t in tareas:
        t_copy = dict(t)
        t_copy["status_col"] = estado
        excel_data.append(t_copy)

if excel_data:
    pd.DataFrame(excel_data).to_excel(os.path.join(DB_DIR, "kanban_report.xlsx"), index=False)