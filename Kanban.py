# -*- coding: utf-8 -*-
"""
Created on Tue Jul  1 21:28:42 2025

@author: acer
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta, datetime # Import datetime for timestamps
import json
import os
import sqlite3
import hashlib # For password hashing
import plotly.express as px # For interactive plotting
import base64 # For encoding/decoding images
from io import BytesIO # For Excel export

st.set_page_config(layout="wide")
st.title("🛠️ Gestión Actividades Kanban Soporte Electrónico")

# ---
# Database Configuration
# ---
DB_DIR = "kanban_db"
os.makedirs(DB_DIR, exist_ok=True)
DB_FILE = os.path.join(DB_DIR, "kanban.db")

def get_db_connection():
    """Establishes and returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # This allows accessing columns by name
    return conn

def init_db():
    """Initializes the database schema and inserts default users if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    """)

    # Create tasks table (removed 'responsible' column)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            date TEXT NOT NULL, -- Fecha de Creación
            priority TEXT NOT NULL,
            shift TEXT NOT NULL,
            status TEXT NOT NULL, -- e.g., 'Por hacer', 'En proceso', 'Hecho'
            completion_date TEXT, -- NULL if not completed
            start_date TEXT, -- New: Fecha Inicial (nullable)
            due_date TEXT, -- New: Fecha Término (nullable)
            description TEXT -- New: Descripción de la tarea (nullable)
        )
    """)

    # New junction table for many-to-many relationship between tasks and users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_collaborators (
            task_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            PRIMARY KEY (task_id, username),
            FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE,
            FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
        )
    """)

    # New table for comments and photo evidence
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            action_type TEXT NOT NULL, -- e.g., 'comment', 'photo_evidence', 'status_change'
            timestamp TEXT NOT NULL,
            comment_text TEXT, -- Nullable
            image_base64 TEXT, -- Nullable (for photo evidence)
            new_status TEXT, -- Nullable (if action_type is 'status_change')
            FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE,
            FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
        )
    """)

    # Insert default users with specific names for roles
    default_users = {
        "Admin User": {"password": "admin_password", "role": "Admin"}, # Example Admin User
        "Erik Armenta": {"password": "colab_password", "role": "Colaborador"} # Example Collaborator
    }
    for username, data in default_users.items():
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        if cursor.fetchone() is None:
            hashed_password = hashlib.sha256(data["password"].encode()).hexdigest()
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                           (username, hashed_password, data["role"]))
            st.success(f"Usuario '{username}' creado (solo la primera vez).") # Informative message on first run

    conn.commit()
    conn.close()

# Initialize the database when the app starts
init_db()

# ---
# User Authentication and Role Management
# ---

# Initialize session state for login status and current role
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "current_role" not in st.session_state:
    st.session_state.current_role = None
if "username" not in st.session_state:
    st.session_state.username = None

def login(username, password):
    """Authenticates user against the database and sets session state."""
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
        st.success(f"¡Bienvenido, {st.session_state.username}! Rol: {st.session_state.current_role}")
        st.rerun() # Rerun to display the app based on the new login state
    else:
        st.error("Usuario o contraseña incorrectos.")

def logout():
    """Logs out the user and resets session state."""
    st.session_state.logged_in = False
    st.session_state.current_role = None
    st.session_state.username = None
    st.info("Has cerrado sesión.")
    st.rerun() # Rerun to display the login form

# ---
# Display Login Form if not logged in
# ---
if not st.session_state.logged_in:
    st.sidebar.header("Inicio de Sesión")
    with st.sidebar.form("login_form"):
        username_input = st.text_input("Usuario")
        password_input = st.text_input("Contraseña", type="password")
        login_button = st.form_submit_button("Iniciar Sesión")
        if login_button:
            login(username_input, password_input)
    st.stop() # Stop execution here if not logged in, to prevent displaying the app content

# ---
# Display Logout Button if logged in
# ---
st.sidebar.header("Sesión Actual")
st.sidebar.write(f"Usuario: **{st.session_state.username}**")
st.sidebar.write(f"Rol: **{st.session_state.current_role}**")
if st.sidebar.button("Cerrar Sesión"):
    logout()

# ---
# Kanban Data Management Functions (using SQLite)
# ---

def load_tasks_from_db():
    """Loads all tasks from the database and organizes them into the kanban session state structure."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Select tasks from the tasks table
    cursor.execute("SELECT * FROM tasks")
    tasks_raw = cursor.fetchall()

    kanban_data = {
        "Por hacer": [],
        "En proceso": [],
        "Hecho": []
    }
    all_tasks_list = []

    for task_row in tasks_raw:
        task_dict = dict(task_row) # Convert Row object to dictionary

        # Fetch collaborators for this task
        collaborators_cursor = conn.execute("SELECT username FROM task_collaborators WHERE task_id = ?", (task_dict['id'],))
        task_dict['responsible_list'] = [row['username'] for row in collaborators_cursor.fetchall()]

        # For display purposes in the dataframe, join them into a string
        task_dict['responsible'] = ", ".join(task_dict['responsible_list'])

        # Fetch the latest comment and image evidence for this task
        latest_interaction_cursor = conn.execute(
            "SELECT comment_text, image_base64, username, timestamp FROM task_interactions WHERE task_id = ? ORDER BY timestamp DESC LIMIT 1",
            (task_dict['id'],)
        )
        latest_interaction = latest_interaction_cursor.fetchone()
        if latest_interaction:
            task_dict['latest_comment'] = latest_interaction['comment_text']
            task_dict['latest_image_base64'] = latest_interaction['image_base64']
            task_dict['latest_comment_user'] = latest_interaction['username']
            task_dict['latest_comment_timestamp'] = latest_interaction['timestamp']
        else:
            task_dict['latest_comment'] = None
            task_dict['latest_image_base64'] = None
            task_dict['latest_comment_user'] = None
            task_dict['latest_comment_timestamp'] = None


        # Ensure 'id' is always present for later updates/deletes
        if 'id' not in task_dict:
            task_dict['id'] = None

        kanban_data[task_dict['status']].append(task_dict)
        all_tasks_list.append(task_dict) # Add to list for DataFrame

    conn.close()
    st.session_state.kanban = kanban_data
    st.session_state.all_tasks_df = pd.DataFrame(all_tasks_list)


# Load tasks immediately after successful login
if st.session_state.logged_in and "kanban" not in st.session_state:
    load_tasks_from_db()
elif st.session_state.logged_in: # Ensure kanban is always loaded/reloaded on app rerun if logged in
    load_tasks_from_db()


def add_task_to_db(task_data, initial_status, responsible_usernames):
    """
    Adds a new task to the database and assigns multiple responsible persons.
    Ensures each responsible person is registered as a collaborator user.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 1. Add the task to the tasks table
        cursor.execute(
            "INSERT INTO tasks (task, date, priority, shift, status, completion_date, start_date, due_date, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_data["tarea"], task_data["fecha"],
             task_data["prioridad"], task_data["turno"], initial_status, None,
             task_data["fecha_inicial"], task_data["fecha_termino"], task_data["description"])
        )
        task_id = cursor.lastrowid # Get the ID of the newly inserted task
        st.success("✅ Tarea agregada a la base de datos.")

        # 2. Add responsible persons to task_collaborators table
        if responsible_usernames:
            for username in responsible_usernames:
                # Check if responsible exists as a user, if not, add them as a collaborator
                cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
                existing_user = cursor.fetchone()

                if existing_user is None:
                    default_collab_password = "colab_nueva_tarea"
                    hashed_default_password = hashlib.sha256(default_collab_password.encode()).hexdigest()
                    # CORRECTED LINE: Use hashed_default_password and "Colaborador" role
                    cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                                   (username, hashed_default_password, "Colaborador"))
                    st.info(f"Nuevo usuario colaborador '{username}' creado con contraseña por defecto: '{default_collab_password}'.")

                # Insert into task_collaborators
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
    load_tasks_from_db() # Reload tasks into session state after adding

def update_task_status_in_db(task_id, new_status, completion_date=None):
    """Updates the status and optionally completion date of a task in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if completion_date:
            cursor.execute(
                "UPDATE tasks SET status = ?, completion_date = ? WHERE id = ?",
                (new_status, completion_date, task_id)
            )
        else:
            cursor.execute(
                "UPDATE tasks SET status = ? WHERE id = ?",
                (new_status, task_id)
            )
        conn.commit()
        st.success("✅ Estado de tarea actualizado en la base de datos.")
    except Exception as e:
        st.error(f"Error al actualizar tarea: {e}")
    finally:
        conn.close()
    load_tasks_from_db() # Reload tasks into session state after updating

def add_task_interaction(task_id, username, action_type, comment_text=None, image_base64=None, new_status=None):
    """Adds an interaction (comment, photo, status change) to the task_interactions table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO task_interactions (task_id, username, action_type, timestamp, comment_text, image_base64, new_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, username, action_type, timestamp, comment_text, image_base64, new_status)
        )
        conn.commit()
        st.success(f"Interacción '{action_type}' registrada.")
    except Exception as e:
        st.error(f"Error al registrar interacción: {e}")
    finally:
        conn.close()
    load_tasks_from_db() # Reload tasks to show new interactions

def update_user_password_in_db(username, new_password):
    """Updates the password for a given user in the database."""
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

def export_and_clear_db():
    """
    Exports all task-related data to an Excel file and then clears
    the tasks, task_collaborators, and task_interactions tables.
    """
    conn = get_db_connection()
    try:
        # 1. Fetch all data
        df_tasks = pd.read_sql_query("SELECT * FROM tasks", conn)
        df_collaborators = pd.read_sql_query("SELECT * FROM task_collaborators", conn)
        df_interactions = pd.read_sql_query("SELECT * FROM task_interactions", conn)

        # Create an in-memory Excel file
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            if not df_tasks.empty:
                df_tasks.to_excel(writer, sheet_name='Tareas', index=False)
            if not df_collaborators.empty:
                df_collaborators.to_excel(writer, sheet_name='Colaboradores_Tareas', index=False)
            if not df_interactions.empty:
                df_interactions.to_excel(writer, sheet_name='Interacciones_Tareas', index=False)

        output.seek(0) # Go to the beginning of the BytesIO object

        # Create a download button for the Excel file
        st.download_button(
            label="Descargar Historial (Excel)",
            data=output,
            file_name=f"kanban_historial_{date.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_db_history"
        )
        st.success("Historial de la base de datos exportado exitosamente.")

        # 2. Clear tables (excluding 'users')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM task_collaborators")
        cursor.execute("DELETE FROM task_interactions")
        cursor.execute("DELETE FROM tasks") # Delete tasks last due to foreign key constraints
        conn.commit()
        st.success("Tablas de tareas, colaboradores e interacciones vaciadas.")

    except Exception as e:
        st.error(f"Error al exportar o vaciar la base de datos: {e}")
    finally:
        conn.close()
    load_tasks_from_db() # Reload tasks to reflect empty state


# --- Function to format task display ---
def formatear_tarea_display(t):
    """
    Formatea los detalles de una tarea para su visualización en las columnas del Kanban.
    Utiliza HTML y CSS en línea para un estilo de tarjeta.
    La tarjeta cambia de color según la fecha de término y el estado.
    """
    card_color = "#393E46" # Default dark grey background

    # Convert dates to datetime.date objects for comparison
    today = date.today()
    task_due_date = None
    if t.get('due_date'):
        try:
            task_due_date = date.fromisoformat(t['due_date'])
        except ValueError:
            pass # Handle cases where date string might be invalid

    # Color logic
    if t['status'] == 'Hecho':
        card_color = "#4CAF50" # Green for completed tasks
    elif t['status'] in ['Por hacer', 'En proceso']:
        if task_due_date:
            if task_due_date <= today:
                card_color = "#F44336" # Red if due date has passed or is today
            elif task_due_date <= today + timedelta(days=3):
                card_color = "#FFC107" # Yellow if due date is within 3 days

    # Ensure all HTML parts are correctly concatenated within the main div
    start_date_display = f"<br><strong>➡️ Inicio:</strong> {t['start_date']}" if t.get('start_date') else ""
    due_date_display = f"<br><strong>🔚 Término:</strong> {t['due_date']}" if t.get('due_date') else ""
    description_display = f"<br><strong>📝 Descripción:</strong> {t['description']}" if t.get('description') else ""

    # Display responsible list - CORRECTED SYNTAX HERE
    responsible_display = ", ".join(t.get('responsible_list', []))
    if not responsible_display:
        responsible_display = "Sin asignar"

    # Latest comment and image display
    latest_comment_html = ""
    if t.get('latest_comment'):
        latest_comment_html += f"<br>---<br><strong>💬 Últ. Comentario:</strong> {t['latest_comment']}<br>"
        latest_comment_html += f"<sub>por {t['latest_comment_user']} el {t['latest_comment_timestamp']}</sub>"
    if t.get('latest_image_base64'):
        if t['latest_image_base64'].strip(): # Check if not empty or just whitespace
            latest_comment_html += f"<br><img src='data:image/png;base64,{t['latest_image_base64']}' style='max-width:100%; height:auto; border-radius:3px; margin-top:5px;'> <br><sub>Últ. Evidencia por {t['latest_comment_user']}</sub>"


    return f"""
    <div style="background-color:{card_color}; color:white; padding: 10px; border-radius: 5px; margin-bottom: 10px;">
        <strong>🔧 Tarea:</strong> {t['task']}
        {description_display}<br>
        <strong>👷 Responsables:</strong> {responsible_display}<br>
        <strong>📅 Creada:</strong> {t['date']}
        {start_date_display}
        {due_date_display}<br>
        <strong>🧭 Turno:</strong> {t['shift']}<br>
        <strong>🔥 Prioridad:</strong> {t['priority']}
        {latest_comment_html}
    </div>
    """

# --- Tab Creation ---
# Conditionally create tabs based on the current role
if st.session_state.current_role == "Admin":
    tab1, tab2, tab3, tab4 = st.tabs(["➕ Agregar Tarea", "📋 Tablero Kanban", "📊 Estadísticas", "⚙️ Gestión Usuarios"])
else: # Colaborador
    tab2, = st.tabs(["📋 Tablero Kanban"]) # Only one tab for Colaborador

# --- Tab 1: Add Task (Admin only) ---
if st.session_state.current_role == "Admin":
    with tab1:
        st.header("➕ Agregar Nueva Tarea")
        st.markdown("---") # Visual separator

        with st.form("agregar_tarea"):
            st.subheader("Detalles de la Tarea")
            tarea = st.text_input("Nombre de la Tarea")
            description = st.text_area("Descripción de la Tarea (Opcional)") # New: Description field

            # Get list of all existing collaborator usernames for multiselect
            conn_users = get_db_connection()
            collab_users_raw = conn_users.execute("SELECT username FROM users WHERE role = 'Colaborador'").fetchall()
            conn_users.close()
            all_collab_usernames = [row['username'] for row in collab_users_raw]

            # Multiselect for existing collaborators
            responsables_existentes_seleccionados = st.multiselect(
                "Seleccionar Responsables Existentes:",
                options=all_collab_usernames,
                default=[],
                key="responsables_existentes_multiselect",
                help="Selecciona uno o más colaboradores de la lista existente."
            )

            # Text input for adding a new collaborator
            nuevo_responsable_input = st.text_input(
                "Añadir Nuevo Colaborador (escribe y presiona Enter):",
                key="nuevo_responsable_text_input",
                help="Si el colaborador no está en la lista de arriba, escribe su nombre aquí. Se creará automáticamente como usuario colaborador con contraseña 'colab_nueva_tarea'."
            )

            # Combine selected existing and new responsible
            responsables_finales = list(responsables_existentes_seleccionados)
            if nuevo_responsable_input and nuevo_responsable_input.strip() not in responsables_finales:
                responsables_finales.append(nuevo_responsable_input.strip())

            fecha = st.date_input("Fecha de Creación", date.today())

            # New date inputs for start and due dates
            fecha_inicial = st.date_input("Fecha Inicial (Opcional)", value=None, key="fecha_inicial_input")
            fecha_termino = st.date_input("Fecha Término (Opcional)", value=None, key="fecha_termino_input")

            prioridad = st.selectbox("Prioridad", ["Alta", "Media", "Baja"])
            turno = st.selectbox("Turno", ["1er Turno", "2do Turno", "3er Turno"])
            # New tasks can only go to "Por hacer" or "En proceso" initially
            destino = st.selectbox("Columna Inicial", ["Por hacer", "En proceso"])
            submit = st.form_submit_button("Crear Tarea")

            if submit and tarea and responsables_finales:
                nueva = {
                    "tarea": tarea,
                    "description": description, # Added description to the task data
                    "fecha": fecha.strftime("%Y-%m-%d"),
                    "prioridad": prioridad,
                    "turno": turno,
                    "fecha_inicial": fecha_inicial.strftime("%Y-%m-%d") if fecha_inicial else None, # Format or None
                    "fecha_termino": fecha_termino.strftime("%Y-%m-%d") if fecha_termino else None # Format or None
                }
                # Pass the list of responsible usernames to add_task_to_db
                add_task_to_db(nueva, destino, responsables_finales)
                st.rerun() # Rerun the app to update state and tabs
            elif submit and (not tarea or not responsables_finales):
                st.error("Por favor, completa el nombre de la tarea y asigna al menos un responsable.")

# --- Tab 2: Kanban Board (Visible to both Admin and Colaborador) ---
with tab2:
    st.header("📋 Tablero Kanban")
    st.markdown("---") # Visual separator

    # Get unique responsible persons for the board filter
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

            # Filter tasks based on the selected user
            visibles = [
                t for t in tareas
                if usuario_actual == "(Todos)" or usuario_actual in t.get("responsible_list", [])
            ]

            if visibles:
                for i, task in enumerate(visibles):
                    st.markdown(formatear_tarea_display(task), unsafe_allow_html=True)

                    # Section for adding comments/evidence and marking as done
                    if estado in ['Por hacer', 'En proceso']:
                        # Only show interaction options if the current user is a responsible for this task (or Admin)
                        if st.session_state.current_role == "Admin" or st.session_state.username in task.get("responsible_list", []):
                            with st.expander(f"Añadir Evidencia / Marcar Hecha para {task['task']}", expanded=False):
                                comment_key = f"comment-{task['id']}-{i}"
                                uploaded_file_key = f"upload-{task['id']}-{i}"

                                comment_text = st.text_area("Comentario:", key=comment_key)
                                uploaded_file = st.file_uploader("Subir Evidencia (PNG/JPG):", type=["png", "jpg", "jpeg"], key=uploaded_file_key)

                                if st.button(f"Guardar Evidencia y Marcar Hecha", key=f"submit_evidence_done-{task['id']}-{i}"):
                                    image_base64 = None
                                    if uploaded_file is not None:
                                        # Read image as bytes and encode to base64
                                        bytes_data = uploaded_file.getvalue()
                                        image_base64 = base64.b64encode(bytes_data).decode('utf-8')
                                        st.success("Imagen cargada y codificada.")

                                    # Update task status
                                    update_task_status_in_db(task['id'], "Hecho", date.today().strftime("%Y-%m-%d"))

                                    # Add interaction record
                                    add_task_interaction(
                                        task_id=task['id'],
                                        username=st.session_state.username,
                                        action_type='status_change_with_evidence',
                                        comment_text=comment_text,
                                        image_base64=image_base64,
                                        new_status="Hecho"
                                    )
                                    st.rerun()

                                if st.button(f"Solo Guardar Comentario/Evidencia", key=f"submit_evidence_only-{task['id']}-{i}"):
                                    image_base64 = None
                                    if uploaded_file is not None:
                                        bytes_data = uploaded_file.getvalue()
                                        image_base64 = base64.b64encode(bytes_data).decode('utf-8')
                                        st.success("Imagen cargada y codificada.")

                                    if comment_text or uploaded_file is not None:
                                        add_task_interaction(
                                            task_id=task['id'],
                                            username=st.session_state.username,
                                            action_type='comment_and_evidence',
                                            comment_text=comment_text,
                                            image_base64=image_base64
                                        )
                                        st.rerun()
                                    else:
                                        st.warning("Por favor, introduce un comentario o sube una imagen para guardar.")
            else:
                st.info("No hay tareas en esta sección.")

# --- Tab 3: Statistics (Admin only) ---
if st.session_state.current_role == "Admin":
    with tab3:
        st.header("📊 Estadísticas del Kanban")
        st.markdown("---") # Visual separator

        if not st.session_state.all_tasks_df.empty:
            df_tasks = st.session_state.all_tasks_df.copy()

            st.subheader("Distribución de Tareas por Estado")
            status_counts = df_tasks['status'].value_counts().reset_index()
            status_counts.columns = ['Estado', 'Número de Tareas']
            fig1 = px.bar(status_counts, x='Estado', y='Número de Tareas', color='Estado',
                          title='Tareas por Estado',
                          labels={'Estado':'Estado de la Tarea', 'Número de Tareas':'Cantidad'})
            st.plotly_chart(fig1, use_container_width=True)

            st.subheader("Tareas Completadas por Responsable")
            completed_tasks_expanded = []
            for index, row in df_tasks[df_tasks['status'] == 'Hecho'].iterrows():
                if 'responsible_list' in row and row['responsible_list']:
                    for resp in row['responsible_list']:
                        completed_tasks_expanded.append({'responsible': resp})

            if completed_tasks_expanded:
                df_completed_expanded = pd.DataFrame(completed_tasks_expanded)
                responsible_counts = df_completed_expanded['responsible'].value_counts().reset_index()
                responsible_counts.columns = ['Responsable', 'Número de Tareas Completadas']
                fig2 = px.bar(responsible_counts, x='Responsable', y='Número de Tareas Completadas', color='Responsable',
                              title='Tareas Completadas por Responsable',
                              labels={'Responsable':'Responsable', 'Número de Tareas Completadas':'Cantidad'})
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("No hay tareas completadas para mostrar estadísticas.")

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

            # --- Graph for Overdue and Soon-to-be-Due Tasks ---
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
                    "Vencida": "#F44336",      # Red
                    "Por Vencer": "#FFEB3B",   # Yellow
                    "A Tiempo": "#4CAF50",     # Green
                    "Sin Fecha de Término": "#808080" # Grey
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

# --- Tab 4: User Management (Admin only) ---
if st.session_state.current_role == "Admin":
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

            st.subheader("Restablecer Contraseña de Usuario")
            with st.form("reset_password_form"):
                users_list = df_users['username'].tolist()
                user_to_reset = st.selectbox("Seleccionar Usuario:", users_list)
                new_password = st.text_input("Nueva Contraseña:", type="password")
                confirm_password = st.text_input("Confirmar Nueva Contraseña:", type="password")
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
        st.warning("¡CUIDADO! Esta acción exportará todos los datos de tareas y luego los eliminará de la base de datos.")
        confirm_clear = st.checkbox("Entiendo que esta acción es irreversible y vaciará las tareas y sus interacciones.", key="confirm_clear_checkbox")
        if confirm_clear:
            if st.button("Exportar y Vaciar Base de Datos", key="export_clear_db_button"):
                export_and_clear_db()
                st.rerun()


# --- Data Export to Excel (Optional, as primary persistence is now SQLite) ---
excel_data = []
for estado, tareas in st.session_state.kanban.items():
    for t in tareas:
        t_copy = dict(t)
        t_copy["status_col"] = estado
        excel_data.append(t_copy)

if excel_data:
    pd.DataFrame(excel_data).to_excel(os.path.join(DB_DIR, "kanban_report.xlsx"), index=False)
else:
    pass