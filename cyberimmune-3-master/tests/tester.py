import requests
import time
import unittest
import random
import json
from datetime import datetime

class CarSharingSystemTest(unittest.TestCase):
    MOBILE_URL = 'http://127.0.0.1:8000'
    PAYMENT_URL = 'http://127.0.0.1:8000'
    CARS_URL = 'http://127.0.0.1:8000'
    MANAGEMENT_URL = 'http://127.0.0.1:8000'
    
    def setUp(self):
        """Setup test data"""
        self.test_clients = [
            {"name": "Иван Иванов", "experience": 1},
            {"name": "Петр Петров", "experience": 0},
            {"name": "Анна Сидорова", "experience": 3}
        ]
        
    def test_01_system_availability(self):
        """Test that all system components are available"""
        services = [
            (self.MOBILE_URL, "Mobile Client"),
            (self.PAYMENT_URL, "Payment System"),
            (self.CARS_URL, "Cars System"),
            (self.MANAGEMENT_URL, "Management System")
        ]
        
        for url, name in services:
            try:
                response = requests.get(f"{url}/car/status/all")
                self.assertIn(response.status_code, [200, 404], f"{name} service is not responding")
            except requests.RequestException as e:
                self.fail(f"{name} service is not available: {str(e)}")

    def test_02_car_listing(self):
        """Test getting available cars"""
        response = requests.get(f"{self.MANAGEMENT_URL}/cars")
        self.assertEqual(response.status_code, 200)
        cars = response.json()
        self.assertIsInstance(cars, list)
        self.assertTrue(len(cars) > 0, "No cars available in the system")

    def test_03_tariff_listing(self):
        """Test getting available tariffs"""
        response = requests.get(f"{self.MANAGEMENT_URL}/tariff")
        self.assertEqual(response.status_code, 200)
        tariffs = response.json()
        self.assertIsInstance(tariffs, list)
        self.assertTrue(len(tariffs) > 0, "No tariffs available in the system")
        self.assertTrue(all(tariff in ["min", "hour"] for tariff in tariffs))

    def test_04_full_rental_cycle(self):
        """Test complete rental cycle for each test client"""
        for client in self.test_clients:
            with self.subTest(client=client):
                # 1. Request car rental
                response = requests.post(f"{self.MOBILE_URL}/cars", json=client)
                self.assertEqual(response.status_code, 200)
                prepayment_data = response.json()
                self.assertIn('id', prepayment_data)
                
                # 2. Confirm prepayment
                response = requests.post(
                    f"{self.MOBILE_URL}/prepayment",
                    json={"id": prepayment_data['id']}
                )
                self.assertEqual(response.status_code, 200)
                
                # 3. Start drive
                response = requests.post(
                    f"{self.MOBILE_URL}/start_drive",
                    json={"name": client['name']}
                )
                self.assertEqual(response.status_code, 200)
                
                # 4. Wait for some trip time
                time.sleep(5)
                
                # 5. Stop drive
                response = requests.post(
                    f"{self.MOBILE_URL}/stop_drive",
                    json={"name": client['name']}
                )
                self.assertEqual(response.status_code, 200)
                invoice_data = response.json()
                self.assertIn('invoice_id', invoice_data)
                
                # 6. Final payment
                response = requests.post(
                    f"{self.MOBILE_URL}/final_pay",
                    json={"invoice_id": invoice_data['invoice_id']}
                )
                self.assertEqual(response.status_code, 200)
                receipt = response.json()
                self.validate_receipt(receipt)

    def test_05_speed_violation_detection(self):
        """Test speed violation detection and penalties"""
        client = self.test_clients[0]
        
        # Start rental process
        response = requests.post(f"{self.MOBILE_URL}/cars", json=client)
        prepayment_data = response.json()
        requests.post(f"{self.MOBILE_URL}/prepayment", json={"id": prepayment_data['id']})
        
        # Start drive
        requests.post(f"{self.MOBILE_URL}/start_drive", json={"name": client['name']})
        
        # Wait for potential speed violations
        time.sleep(10)
        
        # Stop drive
        response = requests.post(f"{self.MOBILE_URL}/stop_drive", json={"name": client['name']})
        invoice_data = response.json()
        
        # Get final receipt
        response = requests.post(
            f"{self.MOBILE_URL}/final_pay",
            json={"invoice_id": invoice_data['invoice_id']}
        )
        receipt = response.json()
        
        # Verify speed violations are recorded and affect final price
        self.assertIn('speed_violations', receipt)

    def test_06_concurrent_rentals(self):
        """Test multiple simultaneous rentals"""
        import threading
        
        def rent_car(client):
            response = requests.post(f"{self.MOBILE_URL}/cars", json=client)
            self.assertEqual(response.status_code, 200)
        
        threads = []
        for client in self.test_clients:
            thread = threading.Thread(target=rent_car, args=(client,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()

    def test_07_invalid_requests(self):
        """Test system's response to invalid requests"""
        # Test invalid client name
        response = requests.post(f"{self.MOBILE_URL}/cars", json={"name": "", "experience": 1})
        self.assertNotEqual(response.status_code, 200)
        
        # Test invalid experience value
        response = requests.post(f"{self.MOBILE_URL}/cars", json={"name": "Test User", "experience": -1})
        self.assertNotEqual(response.status_code, 200)
        
        # Test non-existent car
        response = requests.post(f"{self.CARS_URL}/car/start/nonexistent")
        self.assertEqual(response.status_code, 404)

    def test_08_payment_system(self):
        """Test payment system functionality"""
        # Test client creation
        response = requests.post(f"{self.PAYMENT_URL}/clients", json={"name": "Test Client"})
        self.assertEqual(response.status_code, 201)
        client_data = response.json()[0]
        
        # Test invoice creation
        response = requests.post(f"{self.PAYMENT_URL}/invoices", 
                               json={"client_id": client_data['id'], "amount": 100})
        self.assertEqual(response.status_code, 201)
        invoice_data = response.json()
        
        # Test invoice confirmation
        response = requests.post(f"{self.PAYMENT_URL}/invoices/{invoice_data['id']}/confirm")
        self.assertEqual(response.status_code, 200)

    def validate_receipt(self, receipt):
        """Helper method to validate receipt structure"""
        required_fields = ['car', 'name', 'final_amount', 'created_at', 'elapsed_time', 'tarif']
        for field in required_fields:
            self.assertIn(field, receipt, f"Receipt missing required field: {field}")
        
        self.assertIsInstance(receipt['final_amount'], (int, float))
        self.assertGreater(receipt['final_amount'], 0)
        self.assertIsInstance(receipt['elapsed_time'], (int, float))
        self.assertGreater(receipt['elapsed_time'], 0)

if __name__ == '__main__':
    unittest.main(verbosity=2)
