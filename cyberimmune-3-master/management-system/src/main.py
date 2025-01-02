import requests
import os
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
import threading
from werkzeug.exceptions import HTTPException

HOST = '0.0.0.0'
PORT = 8000
MODULE_NAME = os.getenv('MODULE_NAME')
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///clients.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

PAYMENT_URL = 'http://payment_system:8000'
CARS_URL = 'http://cars:8000'

TARIFF = ["min", "hour"]


# Модель для хранения поездок клиентов
class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_name = db.Column(db.String(100), nullable=False)
    experience = db.Column(db.Integer, nullable=False)
    car = db.Column(db.String(100))
    prepayment = db.Column(db.Integer)
    prepayment_status = db.Column(db.String(100))
    tariff = db.Column(db.String(100))
    elapsed_time = db.Column(db.Float)
    speed_violations = db.Column(db.Integer, default=0)
    zone_violations = db.Column(db.Integer, default=0)


# Инициализация базы данных
@app.before_first_request
def create_tables():
    db.create_all()


def counter_prepayment(car):
    counter = 0
    if car['has_air_conditioner']:
        counter += 7
    if car['has_heater']:
        counter += 5
    if car['has_navigator']:
        counter += 10
    return counter


def counter_payment(trip_time, tariff, experience, speed_violations, zone_violations):
    tariff_min = 2
    tariff_hours = 80
    counter = 0
    if tariff == 'min':
        if experience < 1:
            counter += round(trip_time * tariff_min*2, 2)
        else:
            counter += round(trip_time * tariff_min/experience, 2)
    elif tariff == 'hour':
        if experience < 1:
            counter += round(trip_time * tariff_hours*2, 2)
        else:
            counter += round(trip_time / 10 * tariff_hours/experience, 2)
    
    # Добавляем штраф за превышение скорости
    if speed_violations > 0:
        speed_penalty = speed_violations * 50  # 50 единиц штрафа за каждое нарушение
        counter += speed_penalty
        print(f"Добавлен штраф за превышение скорости: {speed_penalty} (всего нарушений: {speed_violations})")
    
    # Добавляем штраф за выезд из зоны обслуживания
    if zone_violations > 0:
        zone_penalty = zone_violations * 100  # 100 единиц штрафа за каждый выезд из зоны
        counter += zone_penalty
        print(f"Добавлен штраф за выезд из зоны обслуживания: {zone_penalty} (всего нарушений: {zone_violations})")
    
    return counter


# List all avaible cars
@app.route('/cars', methods=['GET'])
def get_all_cars():
    response = requests.get(f'{CARS_URL}/car/status/all')
    if response.status_code == 200:
        cars = response.json()
        avaible_cars = [car['brand'] for car in cars if car['occupied_by'] is None]
        return jsonify(avaible_cars)
    else:
        return jsonify([])


# List all avaible tariff
@app.route('/tariff', methods=['GET'])
def get_tariff():
    return jsonify(TARIFF)


# Handler for telemtry car
@app.route('/telemetry/<string:brand>', methods=['POST'])
def telemetry(brand):
    data = request.json['status']
    speed = data.get('speed')
    coordinates = data.get('coordinates')
    speed_violations = data.get('speed_violations', 0)
    zone_violations = data.get('zone_violations', 0)
    is_in_service_zone = data.get('is_in_service_zone', True)
    status_text = f'"{brand} Скорость: {speed:.2f} км/ч, Координаты: {coordinates}'
    if not is_in_service_zone:
        status_text += f', ВНЕ ЗОНЫ ОБСЛУЖИВАНИЯ!'
    status_text += f', Нарушений скорости: {speed_violations}, Выездов из зоны: {zone_violations}"'
    print(status_text)
    return jsonify(None)


# Handler for access car
@app.route('/access/<string:name>', methods=['POST'])
def access(name):
    client = Client.query.filter_by(client_name=name).one_or_none()
    if client:
        if client.prepayment_status == 'paid':
            print(f"Доступ разрешен {name}")
            return jsonify({'access': True, 'tariff': client.tariff, 'car': client.car})
        else:
            print(f"Доступ запрещён {name}")
            return jsonify({'access': False}), 405
    else:
        print(f"Доступ запрещён {name}")
        return jsonify({'access': False}), 404


# Handler for payment system
@app.route('/confirm_prepayment/<string:name>', methods=['POST'])
def confirm_prepayment(name):
    client = Client.query.filter_by(client_name=name).one_or_none()
    if client:
        client.prepayment_status = request.json['status']
        db.session.commit()
        print(f'Потверждена предоплата: {request.json}')
        return jsonify(request.json)


# Handler for payment system
@app.route('/confirm_payment/<string:name>', methods=['POST'])
def confirm_payment(name):
    client = Client.query.filter_by(client_name=name).one_or_none()
    if client:
        print(f'Потверждена оплата: {request.json}')
        response = requests.get(f'{PAYMENT_URL}/invoices/{request.json["id"]}/receipt')
        if response.status_code == 200:
            receipt = response.json()['receipt']
            final_amount = receipt['amount'] + client.prepayment
            created_at = receipt['created_at']
            final_receipt = {
                'car': client.car,
                'name': client.client_name,
                'final_amount': final_amount,
                'created_at': created_at,
                'elapsed_time': client.elapsed_time,
                'tarif': client.tariff,
                'speed_violations': client.speed_violations,
                'zone_violations': client.zone_violations
            }
            client.car = ''
            client.prepayment = ''
            client.prepayment_status = ''
            client.tariff = ''
            client.elapsed_time = 0
            client.speed_violations = 0
            client.zone_violations = 0
            db.session.commit()
        print(f'Финальный чек: {final_receipt}')
        return jsonify(final_receipt)


# Select car and prepayment calculation
@app.route('/select/car/<string:brand>', methods=['POST'])
def select_car(brand):
    data = request.json
    name = data.get('client_name')
    experience = data.get('experience')
    tariff = data.get('tariff')
    response = requests.post(f'{PAYMENT_URL}/clients', json={'name': name})
    if response.status_code == 201 or 200:
        client = Client.query.filter_by(client_name=name).one_or_none()
        if client is None:
            client = Client(client_name=name, experience=experience)
            db.session.add(client)
            db.session.commit()
        client.car = brand
        client.tariff = tariff
        car = requests.get(f'{CARS_URL}/car/status/{client.car}').json()
        amount = counter_prepayment(car)
        client.prepayment = amount
        db.session.commit()
        print(f'Сформирована предоплата: {client.prepayment}')
        response = requests.post(f'{PAYMENT_URL}/clients/{response.json()[0]["id"]}/prepayment', json={'amount': client.prepayment})

        return jsonify(response.json())
    else:
        print("Ошибка при создании клиента:", response.json())
        return None


# Handler for return car
@app.route('/return/<string:name>', methods=['POST'])
def return_car(name):
    client = Client.query.filter_by(client_name=name).one_or_none()
    if client:
        data = request.json
        trip_time = data.get('status')['trip_time']
        speed_violations = data.get('status')['speed_violations']
        zone_violations = data.get('status')['zone_violations']
        client.elapsed_time = trip_time
        client.speed_violations = speed_violations
        client.zone_violations = zone_violations
        db.session.commit()
        amount = counter_payment(trip_time, client.tariff, client.experience, speed_violations, zone_violations)
        response = requests.post(f'{PAYMENT_URL}/clients', json={'name': name})
        if response.status_code == 201 or 200:
            response = requests.post(f'{PAYMENT_URL}/invoices', json={'client_id': response.json()[0]['id'], 'amount': amount})
            invoice = response.json()
            return jsonify(invoice)
        else:
            print('Нет связи с банком')
        return jsonify({'error': True}), 404
    else:
        print(f"Такой клиент{name} не арендовал машину.")
        return jsonify({'error': True}), 404


@app.errorhandler(HTTPException)
def handle_exception(e):
    response = e.get_response()
    return jsonify({
        "status": e.code,
        "name": e.name,
    }), e.code


def start_web():
    threading.Thread(target=lambda: app.run(
        host=HOST, port=PORT, debug=True, use_reloader=False
    )).start()
