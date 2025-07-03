# -*- coding: utf-8 -*-
"""
Created on Tue Jul  1 21:28:42 2025

@author: acer
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta # Import timedelta for date calculations
import json
import os
import sqlite3
import hashlib # For password hashing
import plotly.express as px # For interactive plotting

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
                card_color = "#FFEB3B" # Yellow if due date is within 3 days

    start_date_display = f"<br><strong>➡️ Inicio:</strong> {t['start_date']}" if t.get('start_date') else ""
    due_date_display = f"<br><strong>🔚 Término:</strong> {t['due_date']}" if t.get('due_date') else ""
    description_display = f"<br><strong>📝 Descripción:</strong> {t['description']}" if t.get('description') else ""

    # Display responsible list
    responsible_display = ", ".join(t.get('responsible_list', [])) # Use 'responsible_list'
    if not responsible_display:
        responsible_display = "Sin asignar"

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

            # Allow adding new responsible names directly in multiselect (Streamlit feature)
            responsables_seleccionados = st.multiselect(
                "Responsables (puedes añadir nuevos nombres):",
                options=all_collab_usernames,
                default=[],
                help="Selecciona uno o más colaboradores. Si escribes un nombre nuevo, se creará un usuario colaborador con contraseña por defecto 'colab_nueva_tarea'."
            )

            # Additional input for new responsible if not in the list (optional, multiselect handles this well)
            # new_responsible_input = st.text_input("Añadir nuevo responsable (si no está en la lista):")
            # if new_responsible_input and new_responsible_input not in responsables_seleccionados:
            #     responsables_seleccionados.append(new_responsible_input)


            fecha = st.date_input("Fecha de Creación", date.today())

            # New date inputs for start and due dates
            fecha_inicial = st.date_input("Fecha Inicial (Opcional)", value=None, key="fecha_inicial_input")
            fecha_termino = st.date_input("Fecha Término (Opcional)", value=None, key="fecha_termino_input")

            prioridad = st.selectbox("Prioridad", ["Alta", "Media", "Baja"])
            turno = st.selectbox("Turno", ["1er Turno", "2do Turno", "3er Turno"])
            # New tasks can only go to "Por hacer" or "En proceso" initially
            destino = st.selectbox("Columna Inicial", ["Por hacer", "En proceso"])
            submit = st.form_submit_button("Crear Tarea")

            if submit and tarea and responsables_seleccionados:
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
                add_task_to_db(nueva, destino, responsables_seleccionados)
                st.rerun() # Rerun the app to update state and tabs
            elif submit and (not tarea or not responsables_seleccionados):
                st.error("Por favor, completa el nombre de la tarea y asigna al menos un responsable.")

# --- Tab 2: Kanban Board (Visible to both Admin and Colaborador) ---
with tab2:
    st.header("📋 Tablero Kanban")
    st.markdown("---") # Visual separator

    # Get unique responsible persons for the board filter
    # Ensures the set of responsible persons updates with new tasks
    # Extracting from st.session_state.kanban which is now loaded from DB
    # We need to get all unique responsible names from the 'responsible_list' in each task
    all_responsibles_flat = []
    for tareas_list in st.session_state.kanban.values():
        for t in tareas_list:
            all_responsibles_flat.extend(t.get('responsible_list', []))
    responsables_para_filtro = sorted(list(set(all_responsibles_flat)))

    default_filter_index = 0
    # If the current user is a collaborator, try to default the filter to their username
    if st.session_state.current_role == "Colaborador" and st.session_state.username in responsables_para_filtro:
        try:
            # Find the index of the logged-in collaborator's username in the list,
            # adding 1 because "(Todos)" is at index 0.
            default_filter_index = responsables_para_filtro.index(st.session_state.username) + 1
        except ValueError:
            pass # If username is not in responsibles (e.g., no tasks assigned yet), keep default to "(Todos)"

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
                    # "Mark as Done" button for tasks in "Por hacer" and "En proceso"
                    if estado in ["Por hacer", "En proceso"]:
                        # Admin can mark any task as done
                        if st.session_state.current_role == "Admin":
                            if st.button(f"✅ Marcar como hecha: {task['task']}", key=f"done-{estado}-{task['id']}-{i}"):
                                update_task_status_in_db(task['id'], "Hecho", date.today().strftime("%Y-%m-%d"))
                                st.rerun() # Rerun to reflect the change in the "Hecho" column
                        # Colaborador can only mark their own tasks as done
                        elif st.session_state.current_role == "Colaborador":
                            # The button appears ONLY if the logged-in username is in the task's responsible list
                            if st.session_state.username in task.get("responsible_list", []):
                                if st.button(f"✅ Marcar como hecha: {task['task']}", key=f"done-{estado}-{task['id']}-{i}"):
                                    update_task_status_in_db(task['id'], "Hecho", date.today().strftime("%Y-%m-%d"))
                                    st.rerun() # Rerun to reflect the change in the "Hecho" column
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
            # This graph needs adjustment if 'responsible' in df_tasks is now a comma-separated string
            # For simplicity, we'll count tasks where the logged-in user is *one of* the responsible parties
            # Or, we can count total tasks completed by each responsible, which requires a bit more flattening.
            # Let's flatten the responsible list for this graph.
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
            # Define a consistent order for priorities
            priority_order = ["Alta", "Media", "Baja"]
            priority_counts['Prioridad'] = pd.Categorical(priority_counts['Prioridad'], categories=priority_order, ordered=True)
            priority_counts = priority_counts.sort_values('Prioridad')

            fig3 = px.pie(priority_counts, values='Cantidad', names='Prioridad',
                          title='Tareas por Prioridad',
                          hole=0.3) # Adds a donut hole for better aesthetics
            st.plotly_chart(fig3, use_container_width=True)

            # --- Graph for Overdue and Soon-to-be-Due Tasks ---
            st.subheader("Estado de Actividades por Vencimiento")

            # Filter tasks that are not yet 'Hecho'
            pending_tasks = df_tasks[df_tasks['status'].isin(['Por hacer', 'En proceso'])].copy()

            if not pending_tasks.empty:
                today = date.today()

                # Convert 'due_date' to datetime.date objects, handling potential None values
                pending_tasks['due_date_obj'] = pending_tasks['due_date'].apply(
                    lambda x: date.fromisoformat(x) if pd.notna(x) else None
                )

                # Categorize tasks based on due date
                def categorize_due_date(row):
                    if row['due_date_obj'] is None:
                        return "Sin Fecha de Término"
                    elif row['due_date_obj'] <= today:
                        return "Vencida"
                    elif row['due_date_obj'] <= today + timedelta(days=7): # Within next 7 days
                        return "Por Vencer"
                    else:
                        return "A Tiempo"

                pending_tasks['Estado Vencimiento'] = pending_tasks.apply(categorize_due_date, axis=1)

                due_date_counts = pending_tasks['Estado Vencimiento'].value_counts().reset_index()
                due_date_counts.columns = ['Categoría', 'Número de Tareas']

                # Define a specific order for the categories for consistent plotting
                category_order = ["Vencida", "Por Vencer", "A Tiempo", "Sin Fecha de Término"]
                due_date_counts['Categoría'] = pd.Categorical(due_date_counts['Categoría'], categories=category_order, ordered=True)
                due_date_counts = due_date_counts.sort_values('Categoría')

                # Define colors for the categories
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
            # --- End New Graph ---

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
                        st.rerun() # Rerun to refresh the user list/feedback
                    elif not new_password:
                        st.warning("Por favor, introduce una nueva contraseña.")
                    else:
                        st.error("Las contraseñas no coinciden.")
        else:
            st.info("No hay usuarios registrados en la base de datos.")


# --- Data Export to Excel (Optional, as primary persistence is now SQLite) ---
# This part is kept for generating an Excel report if needed,
# but the primary data source is SQLite.
excel_data = []
for estado, tareas in st.session_state.kanban.items():
    for t in tareas:
        t_copy = dict(t) # Convert Row object to dictionary if it's not already
        # Use the 'responsible' key which is now a comma-separated string for Excel export
        t_copy["status_col"] = estado
        excel_data.append(t_copy)

# Ensure data is not empty before creating DataFrame
if excel_data:
    pd.DataFrame(excel_data).to_excel(os.path.join(DB_DIR, "kanban_report.xlsx"), index=False)
    st.success("✅ Reporte Excel actualizado en la carpeta 'kanban_db'.")
else:
    st.info("No hay tareas para exportar a Excel.")