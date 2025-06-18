from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///workout.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Ensure backups directory exists
BACKUP_DIR = os.path.join(os.path.dirname(__file__), 'backups')
os.makedirs(BACKUP_DIR, exist_ok=True)

# Database Models
class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    date = db.Column(db.Date)
    duration = db.Column(db.Integer)  # in seconds
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Exercise(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)

class WorkoutSet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    workout_id = db.Column(db.Integer, db.ForeignKey('workout.id'))
    exercise_id = db.Column(db.Integer, db.ForeignKey('exercise.id'))
    set_number = db.Column(db.Integer)
    weight = db.Column(db.Float)
    reps = db.Column(db.Integer)
    f = db.Column(db.Integer, nullable=True)  # Perceived effort (1-6, null if "-")
    c = db.Column(db.Integer, nullable=True)  # Cardio effort (1-6, null if "-")
    notes = db.Column(db.Text)
    workout = db.relationship('Workout', backref='sets')

class Preset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    exercises = db.Column(db.JSON)  # list of {exercise_id, sets, order}

# Create database tables
with app.app_context():
    db.create_all()

# Routes
@app.route('/')
def main_menu():
    return render_template('main_menu.html')

@app.route('/workout')
def workout():
    presets = Preset.query.all()
    return render_template('workout.html', presets=presets)

@app.route('/workout/<int:preset_id>', methods=['GET', 'POST'])
def workout_form_preset(preset_id):
    preset = Preset.query.get_or_404(preset_id)
    if request.method == 'POST':
        return save_workout()
    return render_template('workout_form.html', preset=preset, exercises=[])

@app.route('/preset/<int:preset_id>/exercises')
def preset_exercises(preset_id):
    preset = Preset.query.get_or_404(preset_id)
    exercises = []
    for ex in sorted(preset.exercises, key=lambda x: x.get('order', 0) if isinstance(x, dict) else 0):
        if isinstance(ex, int):
            exercise = Exercise.query.get(ex)
            if exercise:
                exercises.append({'id': exercise.id, 'name': exercise.name, 'sets': 3, 'order': 0})
        elif isinstance(ex, dict) and 'exercise_id' in ex:
            exercise = Exercise.query.get(ex['exercise_id'])
            if exercise:
                exercises.append({
                    'id': exercise.id,
                    'name': exercise.name,
                    'sets': ex.get('sets', 3),
                    'order': ex.get('order', 0)
                })
    return jsonify(exercises)

@app.route('/workout/custom', methods=['GET', 'POST'])
def workout_form_custom():
    if request.method == 'POST':
        return save_workout()
    return render_template('workout_form.html', preset=None, exercises=[])

def save_workout():
    title = request.form['title']
    duration = int(request.form['duration'])
    workout = Workout(title=title, date=datetime.now().date(), duration=duration)
    db.session.add(workout)
    db.session.flush()

    exercise_indices = set()
    for key in request.form.keys():
        if 'exercises[' in key and key.count('[') >= 2:
            try:
                idx = key.split('[')[1].split(']')[0]
                exercise_indices.add(idx)
            except IndexError:
                continue

    workout_data = {
        'id': workout.id,
        'title': title,
        'date': str(workout.date),
        'duration': duration,
        'exercises': []
    }

    for idx in sorted(exercise_indices, key=int):
        exercise_name = request.form.get(f'exercises[{idx}][name]')
        exercise_id = request.form.get(f'exercises[{idx}][exercise_id]')
        order = int(request.form.get(f'exercises[{idx}][order]', idx))
        if exercise_name:
            exercise = Exercise.query.filter_by(name=exercise_name).first()
            if not exercise:
                exercise = Exercise(name=exercise_name)
                db.session.add(exercise)
                db.session.flush()
        elif exercise_id:
            exercise = Exercise.query.get(int(exercise_id))
            if not exercise:
                continue
        else:
            continue

        set_indices = set()
        for key in request.form.keys():
            if f'exercises[{idx}][sets][' in key and key.count('[') >= 4:
                try:
                    set_idx = key.split('[')[3].split(']')[0]
                    int(set_idx)
                    set_indices.add(set_idx)
                except (ValueError, IndexError):
                    continue

        exercise_data = {
            'name': exercise.name,
            'order': order,
            'sets': []
        }

        for set_idx in sorted(set_indices, key=int):
            weight = float(request.form.get(f'exercises[{idx}][sets][{set_idx}][weight]', 0) or 0)
            reps = int(request.form.get(f'exercises[{idx}][sets][{set_idx}][reps]', 0) or 0)
            f = request.form.get(f'exercises[{idx}][sets][{set_idx}][f]')
            f = int(f) if f and f != '-' else None
            c = request.form.get(f'exercises[{idx}][sets][{set_idx}][c]')
            c = int(c) if c and c != '-' else None
            notes = request.form.get(f'exercises[{idx}][sets][{set_idx}][notes]', '')
            workout_set = WorkoutSet(
                workout_id=workout.id,
                exercise_id=exercise.id,
                set_number=int(set_idx) + 1,
                weight=weight,
                reps=reps,
                f=f,
                c=c,
                notes=notes
            )
            db.session.add(workout_set)
            exercise_data['sets'].append({
                'set_number': int(set_idx) + 1,
                'weight': weight,
                'reps': reps,
                'f': f,
                'c': c,
                'notes': notes
            })

        workout_data['exercises'].append(exercise_data)

    db.session.commit()

    # Save workout as JSON
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = os.path.join(BACKUP_DIR, f'workout_{workout.id}_{timestamp}.json')
    with open(backup_file, 'w') as f:
        json.dump(workout_data, f, indent=2)

    num_exercises = len(exercise_indices)
    return redirect(url_for('confirmation', duration=duration, num_exercises=num_exercises))

@app.route('/confirmation')
def confirmation():
    duration = request.args.get('duration', type=int)
    num_exercises = request.args.get('num_exercises', type=int)
    return render_template('confirmation.html', duration=duration, num_exercises=num_exercises)

@app.route('/past_workouts')
def past_workouts():
    workouts = Workout.query.order_by(Workout.date.desc()).all()
    return render_template('past_workouts.html', workouts=workouts)

@app.route('/past_workouts/<int:workout_id>')
def workout_details(workout_id):
    workout = Workout.query.get_or_404(workout_id)
    sets = WorkoutSet.query.filter_by(workout_id=workout_id).order_by(WorkoutSet.set_number).all()
    exercises = {}
    for s in sets:
        if s.exercise_id not in exercises:
            exercise = Exercise.query.get(s.exercise_id)
            exercises[s.exercise_id] = {
                'name': exercise.name,
                'order': s.set_number,  # Use first set's order as proxy
                'sets': []
            }
        exercises[s.exercise_id]['sets'].append(s)
    # Sort exercises by order, then sort sets within each exercise
    sorted_exercises = sorted(exercises.items(), key=lambda x: x[1]['order'])
    for _, ex in sorted_exercises:
        ex['sets'].sort(key=lambda s: s.set_number)
    return render_template('workout_details.html', workout=workout, exercises=sorted_exercises)

@app.route('/past_exercises')
def past_exercises():
    exercises = Exercise.query.all()
    return render_template('past_exercises.html', exercises=exercises)

@app.route('/past_exercises/<int:exercise_id>')
def exercise_history(exercise_id):
    exercise = Exercise.query.get_or_404(exercise_id)
    sets = WorkoutSet.query.filter_by(exercise_id=exercise_id).order_by(WorkoutSet.workout_id.desc()).all()
    filter_days = request.args.get('filter', default=None)
    if filter_days == '30days':
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=30)
        sets = [s for s in sets if s.workout.date >= cutoff.date()]
    return render_template('exercise_history.html', exercise=exercise, sets=sets)

@app.route('/analysis')
def analysis():
    return render_template('analysis.html')

@app.route('/exercises/autocomplete')
def exercises_autocomplete():
    term = request.args.get('term', '')
    exercises = Exercise.query.filter_by(name=term).first()
    if not exercises:
        exercises = Exercise(name=term)
        db.session.add(exercises)
        db.session.commit()
    return jsonify({'id': exercises.id, 'name': exercises.name})

@app.route('/preset/new', methods=['GET', 'POST'])
def preset_new():
    if request.method == 'POST':
        name = request.form['name']
        exercise_indices = set([k.split('[')[1].split(']')[0] for k in request.form.keys() if 'exercises[' in k and k.count('[') >= 2])
        exercises = []
        for idx in exercise_indices:
            exercise_name = request.form.get(f'exercises[{idx}][name]')
            if not exercise_name:
                continue
            exercise = Exercise.query.filter_by(name=exercise_name).first()
            if not exercise:
                exercise = Exercise(name=exercise_name)
                db.session.add(exercise)
                db.session.flush()
            set_count = int(request.form.get(f'exercises[{idx}][set_count]', 1))
            order = int(request.form.get(f'exercises[{idx}][order]', len(exercises) + 1))
            exercises.append({'exercise_id': exercise.id, 'sets': set_count, 'order': order})
        if name and exercises:
            preset = Preset(name=name, exercises=exercises)
            db.session.add(preset)
            db.session.commit()
            return redirect(url_for('workout'))
    return render_template('preset_form.html', preset=None)

@app.route('/preset/<int:preset_id>/edit', methods=['GET', 'POST'])
def preset_edit(preset_id):
    preset = Preset.query.get_or_404(preset_id)
    if request.method == 'POST':
        if 'delete' in request.form:
            db.session.delete(preset)
            db.session.commit()
            return redirect(url_for('workout'))
        name = request.form['name']
        exercise_indices = set([k.split('[')[1].split(']')[0] for k in request.form.keys() if 'exercises[' in k and k.count('[') >= 2])
        exercises = []
        for idx in exercise_indices:
            exercise_name = request.form.get(f'exercises[{idx}][name]')
            if not exercise_name:
                continue
            exercise = Exercise.query.filter_by(name=exercise_name).first()
            if not exercise:
                exercise = Exercise(name=exercise_name)
                db.session.add(exercise)
                db.session.flush()
            set_count = int(request.form.get(f'exercises[{idx}][set_count]', 1))
            order = int(request.form.get(f'exercises[{idx}][order]', len(exercises) + 1))
            exercises.append({'exercise_id': exercise.id, 'sets': set_count, 'order': order})
        if name and exercises:
            preset.name = name
            preset.exercises = exercises
            db.session.commit()
            return redirect(url_for('workout'))
    exercises = []
    for ex in preset.exercises:
        if isinstance(ex, int):
            exercise = Exercise.query.get(ex)
            if exercise:
                exercises.append({'id': exercise.id, 'name': exercise.name, 'sets': 3, 'order': 0})
        elif isinstance(ex, dict) and 'exercise_id' in ex:
            exercise = Exercise.query.get(ex['exercise_id'])
            if exercise:
                exercises.append({
                    'id': exercise.id,
                    'name': exercise.name,
                    'sets': ex.get('sets', 3),
                    'order': ex.get('order', len(exercises) + 1)
                })
    return render_template('preset_form.html', preset=preset, exercises=exercises)

if __name__ == '__main__':
    app.run(debug=True)

# Add sample presets for testing
with app.app_context():
    if not Preset.query.first():
        push_exercises = [Exercise(name="Bench Press"), Exercise(name="Push Up")]
        db.session.add_all(push_exercises)
        db.session.flush()
        db.session.add(Preset(name="2025-06-Push", exercises=[
            {'exercise_id': push_exercises[0].id, 'sets': 3, 'order': 1},
            {'exercise_id': push_exercises[1].id, 'sets': 3, 'order': 2}
        ]))
        db.session.commit()