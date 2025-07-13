import sqlite3
import os
from flask import Flask, render_template, request, redirect, url_for, g, flash, session, jsonify
from functools import wraps

# --- CONFIGURACIÓN Y CONSTANTES ---
DATABASE = 'Frases__DB.db'
SECRET_KEY = os.urandom(24)
ADMIN_KEY = os.environ.get('ADMIN_KEY', 'default_admin_key')
GUEST_KEY = os.environ.get('GUEST_KEY', 'default_guest_key')
SECRET_KEY = os.environ.get('SECRET_KEY', 'un_secreto_muy_fuerte')
ACCESS_KEY = os.environ.get('ADMIN_KEY', 'default_admin_key')
VALID_LOOKUP_TABLES = {'F_Tema', 'F_Autor', 'F_Tipo'} # Usamos un 'set' para búsquedas más rápidas
app = Flask(__name__)
app.config.from_object(__name__)

# --- GESTIÓN DE LA BASE DE DATOS ---
def get_db():
    if not hasattr(g, 'sqlite_db'):
        g.sqlite_db = sqlite3.connect(DATABASE)
        g.sqlite_db.row_factory = sqlite3.Row
    return g.sqlite_db
@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'sqlite_db'):
        g.sqlite_db.close()
def get_lookup_data():
    db = get_db()
    cursor = db.cursor()
    data = {
        'temas': cursor.execute("SELECT X, Nombre FROM F_Tema ORDER BY Nombre").fetchall(),
        'autores': cursor.execute("SELECT X, Nombre FROM F_Autor ORDER BY Nombre").fetchall(),
        'tipos': cursor.execute("SELECT X, Nombre FROM F_Tipo ORDER BY Nombre").fetchall()}
        # Nota: No incluimos subtemas aquí porque son dinámicos y dependen de la selección de un tema.
    return data
def validate_subtema(tema_id, subtema_id):
    db = get_db()
    if not subtema_id or not tema_id: return True         
    subtema = db.execute(
        "SELECT X FROM F_Subtema WHERE X = ? AND Tema_X = ?", (subtema_id, tema_id)).fetchone()
    return subtema is not None
def json_success(message, **kwargs):
    """Genera una respuesta JSON estándar para operaciones exitosas."""
    response = {'success': True, 'message': message}
    response.update(kwargs)
    return jsonify(response)
def json_error(message, status_code=400):
    """Genera una respuesta JSON estándar para errores."""
    return jsonify({'success': False, 'message': message}), status_code
# --- AUTENTICACIÓN ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        clave = request.form.get('clave')
        if clave == app.config['ADMIN_KEY']:
            session['logged_in'] = True
            session['user_role'] = 'admin' # Store role as 'admin'
            return redirect(url_for('index'))
        elif clave == app.config['GUEST_KEY']:
            session['logged_in'] = True
            session['user_role'] = 'guest' # Store role as 'guest'
            return redirect(url_for('index'))
        else:
            flash('Clave de acceso incorrecta', 'danger')
    return render_template('Frases_Acceso.html')
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('Has cerrado la sesión.', 'info')
    return redirect(url_for('login'))

# --- VISTAS PRINCIPALES ---
@app.route('/')
@login_required
def index():
    db = get_db()
    lookup_data = get_lookup_data()
    
    # --- 1. Build Search Query based on URL arguments ---
    args = request.args
    search_query_text = args.get('q', '').strip()
    
    conditions, params = [], []
    summary_parts = []

    # Build conditions for the SQL query and parts for the summary message
    if search_query_text:
        if search_query_text in ['*','#']:
            if search_query_text == '*':
                # Buscar todos los Favoritos (campo Favorito = 'SI')
                conditions.append("p.Favorito = 'SI'")
                summary_parts.append("Favoritos")
            else:
                conditions.append("p.Divertido = 'SI'")
                summary_parts.append("Divertidos")
        else:
            conditions.append("p.Frase LIKE ?")
            params.append(f'%{search_query_text}%')
            summary_parts.append(f"Texto: '{search_query_text}'")

    # This logic already handles independent filters correctly.
    # Selecting a Tema does NOT require a Subtema.
    if args.get('tema'):
        conditions.append("p.Tema_x = ?")
        params.append(args.get('tema'))
        # Fetch the name for the summary
        tema_name = db.execute("SELECT Nombre FROM F_Tema WHERE X = ?", (args.get('tema'),)).fetchone()
        if tema_name: summary_parts.append(f"Tema: {tema_name['Nombre']}")
            
    if args.get('subtema'):
        conditions.append("p.Subtema_x = ?")
        params.append(args.get('subtema'))
        subtema_name = db.execute("SELECT Nombre FROM F_Subtema WHERE X = ?", (args.get('subtema'),)).fetchone()
        if subtema_name: summary_parts.append(f"Subtema: {subtema_name['Nombre']}")

    if args.get('autor'):
        conditions.append("p.Autor_x = ?")
        params.append(args.get('autor'))
        autor_name = db.execute("SELECT Nombre FROM F_Autor WHERE X = ?", (args.get('autor'),)).fetchone()
        if autor_name: summary_parts.append(f"Autor: {autor_name['Nombre']}")

    if args.get('tipo'):
        conditions.append("p.Tipo_x = ?")
        params.append(args.get('tipo'))
        tipo_name = db.execute("SELECT Nombre FROM F_Tipo WHERE X = ?", (args.get('tipo'),)).fetchone()
        if tipo_name: summary_parts.append(f"Tipo: {tipo_name['Nombre']}")

    # --- 2. Execute Query ---
    base_query = """
        SELECT p.X, p.Frase, p.Significado, p.Favorito, p.Divertido,
               t.Nombre as Tema, s.Nombre as Subtema, a.Nombre as Autor, ti.Nombre as Tipo
        FROM Frases p
        LEFT JOIN F_Tema t ON p.Tema_x = t.X
        LEFT JOIN F_Subtema s ON p.Subtema_x = s.X
        LEFT JOIN F_Autor a ON p.Autor_x = a.X
        LEFT JOIN F_Tipo ti ON p.Tipo_x = ti.X
    """
    
    frases = []
    search_summary = ""
    frase_del_dia = None
        # Only search if there are actual search terms
    if conditions:
        query = base_query + " WHERE " + " AND ".join(conditions)
        search_summary = "Búsqueda: " + ", ".join(summary_parts)
        if search_query_text in ['*','#']:
            frases = db.execute(query).fetchall()
        else:
            frases = db.execute(query, params).fetchall()
        
    # --- 3. Handle No Results / Initial Load ---
    if not frases:
        # Fetch a single random phrase to display as "Phrase of the Day"
        frase_del_dia = db.execute(base_query + " WHERE p.Favorito = 'SI' ORDER BY RANDOM() LIMIT 1").fetchone()
        if not frase_del_dia:
            frase_del_dia = db.execute(base_query + " ORDER BY RANDOM() LIMIT 1").fetchone()
    # The search values are passed back to the template to keep the form populated.
    # This is standard UX and better than clearing the form.
    return render_template('index.html', 
                           frases=frases, 
                           frase_del_dia=frase_del_dia,
                           search_summary=search_summary,
                           total_frases=len(frases),
                           search_values=args, 
                           **lookup_data)

# --- RUTAS DE CONTENIDO PARA MODALES ---
@app.route('/frase/new/content')
@login_required
def new_frase_content():
    lookup_data = get_lookup_data()
    return render_template('Frases_CRUD.html', action_url=url_for('add_frase'), title='Agregar Frase', subtemas=[], **lookup_data)
@app.route('/frase/edit/<int:id>/content')
@login_required
def edit_frase_content(id):
    db = get_db()
    frase = db.execute("SELECT * FROM Frases WHERE X = ?", (id,)).fetchone()
    if not frase: return "Frase no encontrada", 404
    lookup_data = get_lookup_data()
    subtemas = db.execute("SELECT * FROM F_Subtema WHERE Tema_x = ? ORDER BY Nombre", (frase['Tema_x'],)).fetchall() if frase['Tema_x'] else []
    return render_template('Frases_CRUD.html', action_url=url_for('edit_frase', id=id), title='Editar Frase', frase=frase, subtemas=subtemas, **lookup_data)
@app.route('/manage/content')
@login_required
def manage_content():
    lookup_data = get_lookup_data()
    return render_template('Frases_Tablas_CRUD.html', ** lookup_data)

# --- RUTAS DE PROCESAMIENTO (API) ---
@app.route('/frase/add', methods=['POST'])
@login_required
def add_frase():
    form_data = request.form
    tema_id = form_data.get('tema_x')
    subtema_id = form_data.get('subtema_x')
    if not validate_subtema(tema_id, subtema_id):
        return json_error("El subtema seleccionado no pertenece al tema elegido.")
    try:    
        db = get_db()
        db.execute(
            "INSERT INTO Frases (Frase, Significado, Favorito, Divertido, Tema_x, Subtema_x, Autor_x, Tipo_x) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (form_data['frase'], form_data['significado'], form_data.get('favorito', 'NO'), form_data.get('divertido', 'NO'),
             tema_id, subtema_id, form_data['autor_x'], form_data['tipo_x']))
        db.commit()
        return json_success('Frase agregada exitosamente.')
    except Exception as e:
        return json_error(f'Error al agregar: {e}')
@app.route('/frase/edit/<int:id>', methods=['POST'])
@login_required
def edit_frase(id):
    form_data = request.form
    tema_id = form_data.get('tema_x')
    subtema_id = form_data.get('subtema_x')
    if not validate_subtema(tema_id, subtema_id):
        return json_error("El subtema seleccionado no pertenece al tema elegido.")
    try:
        db = get_db()
        db.execute(
            "UPDATE Frases SET Frase=?, Significado=?, Favorito=?, Divertido=?, Tema_x=?, Subtema_x=?, Autor_x=?, Tipo_x=? WHERE X=?",
            (form_data['frase'], form_data['significado'], form_data.get('favorito', 'NO'), form_data.get('divertido', 'NO'),
             tema_id, subtema_id, form_data['autor_x'], form_data['tipo_x'], id)
        )
        db.commit()
        return json_success('Frase actualizada correctamente.')
    except Exception as e:
        return json_error(f'Error al actualizar: {e}')
@app.route('/frase/delete/<int:id>', methods=['POST'])
@login_required
def delete_frase(id):
    db = get_db()
    try:
        db.execute("DELETE FROM Frases WHERE X = ?", (id,))
        db.commit()
        flash('Frase eliminada exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al eliminar la frase: {e}', 'danger')
    return redirect(url_for('index'))

# --- RUTAS DE PROCESAMIENTO PARA GESTIONAR TABLAS (API) ---

@app.route('/manage/add/<tabla>', methods=['POST'])
@login_required
def add_lookup(tabla):
    if tabla not in VALID_LOOKUP_TABLES:
        return json_error('Tabla no válida.')
    
    nombre = request.form.get('nombre', '').strip()
    if not nombre:
        return json_error('El nombre no puede estar vacío.')
    
    try:
        db = get_db()
        db.execute(f"INSERT INTO {tabla} (Nombre) VALUES (?)", (nombre,))
        db.commit()
        return json_success(f'Elemento "{nombre}" agregado a {tabla}.')
    except sqlite3.IntegrityError:
        return json_error(f'El elemento "{nombre}" ya existe.', 409)
    except Exception as e:
        return json_error(str(e))

@app.route('/manage/delete/<tabla>/<int:id>', methods=['POST'])
@login_required
def delete_lookup(tabla, id):
    if tabla not in VALID_LOOKUP_TABLES:
        return json_error('Tabla no válida.')
    
    db = get_db()
    try:
        fk_map = {'F_Tema': 'Tema_x', 'F_Autor': 'Autor_x', 'F_Tipo': 'Tipo_x'}
        count = db.execute(f"SELECT COUNT(*) FROM Frases WHERE {fk_map[tabla]} = ?", (id,)).fetchone()[0]
        if count > 0:
            return json_error(f'No se puede eliminar. El elemento está en uso por {count} frase(s).', 409)

        if tabla == 'F_Tema':
            db.execute("DELETE FROM F_Subtema WHERE Tema_x = ?", (id,))

        db.execute(f"DELETE FROM {tabla} WHERE X = ?", (id,))
        db.commit()
        return json_success('Elemento eliminado correctamente.')
    except Exception as e:
        return json_error(f'Error al eliminar: {e}')

@app.route('/manage/add_subtema', methods=['POST'])
@login_required
def add_subtema():
    tema_id = request.form.get('tema_id')
    nombre = request.form.get('nombre', '').strip()

    if not tema_id or not nombre:
        return json_error('Se requiere un tema y un nombre para el subtema.')
    
    try:
        db = get_db()
        db.execute("INSERT INTO F_Subtema (Nombre, Tema_X) VALUES (?, ?)", (nombre, tema_id))
        db.commit()
        return json_success(f'Subtema "{nombre}" agregado.')
    except sqlite3.IntegrityError:
        return json_error('Este subtema ya existe para el tema seleccionado.', 409)
    except Exception as e:
        return json_error(str(e))

@app.route('/manage/delete_subtema/<int:id>', methods=['POST'])
@login_required
def delete_subtema(id):
    db = get_db()
    try:
        count = db.execute("SELECT COUNT(*) FROM Frases WHERE Subtema_x = ?", (id,)).fetchone()[0]
        if count > 0:
            return json_error(f'No se puede eliminar. El subtema está en uso por {count} frase(s).', 409)

        db.execute("DELETE FROM F_Subtema WHERE X = ?", (id,))
        db.commit()
        return json_success('Subtema eliminado.')
    except Exception as e:
        return json_error(f'Error al eliminar el subtema: {e}')
        
# --- API ENDPOINT PARA SUBTEMAS DINÁMICOS ---

@app.route('/api/subtemas/<int:tema_id>')
@login_required
def get_subtemas(tema_id):
    db = get_db()
    subtemas = db.execute("SELECT X, Nombre FROM F_Subtema WHERE Tema_X = ? ORDER BY Nombre", (tema_id,)).fetchall()
    return jsonify([dict(row) for row in subtemas])

# NUEVO: Endpoint para obtener datos para la nueva interfaz de gestión
@app.route('/api/manage_data/<table>')
@login_required
def get_manage_data(table):  # Asegúrate que el parámetro sea 'table'
    # Validar tabla permitida
    if table not in VALID_LOOKUP_TABLES:
        return json_error('Tabla no válida.', 404)

    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str).strip()
    limit = 5
    offset = (page - 1) * limit

    db = get_db()
    params = []
    where_clause = ""
    
    # Buscar por cualquier campo que contenga el texto
    if search:
        # IMPORTANTE: Asegúrate que tus tablas tienen una columna "Nombre"
        where_clause = " WHERE Nombre LIKE ?"
        params.append(f'%{search}%')
    
    # Consulta para contar total de registros
    count_query = f"SELECT COUNT(*) FROM {table}{where_clause}"
    total_items = db.execute(count_query, params).fetchone()[0]
    total_pages = (total_items + limit - 1) // limit

    # Consulta para obtener datos
    # IMPORTANTE: Asegúrate que todas tus tablas tienen columnas "X" e "Nombre"
    data_query = f"SELECT X, Nombre FROM {table}{where_clause} ORDER BY Nombre LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    try:
        items = db.execute(data_query, params).fetchall()
    except sqlite3.OperationalError as e:
        # Manejar errores de estructura de tabla
        return json_error(f"Error en la tabla: {str(e)}", 500)

    return jsonify({
        'items': [dict(row) for row in items],
        'pagination': {
            'page': page,
            'total_pages': total_pages,
            'total_items': total_items
        }
    })

# NUEVO: Endpoint para actualizar un registro existente (para el botón de editar)
@app.route('/manage/update/<table>/<int:id>', methods=['POST'])
@login_required
def update_lookup(table, id):
    if table not in VALID_LOOKUP_TABLES:
        return json_error('Tabla no válida.')
    
    nombre = request.form.get('nombre', '').strip()
    if not nombre:
        return json_error('El nombre no puede estar vacío.')

    try:
        db = get_db()
        db.execute(f"UPDATE {table} SET Nombre = ? WHERE X = ?", (nombre, id))
        db.commit()
        return json_success(f'Elemento actualizado a "{nombre}".')
    except sqlite3.IntegrityError:
        return json_error(f'El nombre "{nombre}" ya existe.', 409)
    except Exception as e:
        return json_error(str(e))

# --- PUNTO DE ENTRADA  ---
if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        print(f"Error: La base de datos '{DATABASE}' no se encontró.")
    else:
        print(f"Iniciando servidor web...")
        print(f"Tu clave de acceso es: {ACCESS_KEY}")
        print(f"Abre tu navegador y ve a http://127.0.0.1:5000")
        # El modo debug=True NUNCA debe usarse en producción
        app.run(debug=False, host='0.0.0.0')
      