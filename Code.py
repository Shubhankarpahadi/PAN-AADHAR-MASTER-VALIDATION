from flask import Flask, render_template, request, send_file, jsonify, session
import pandas as pd
import csv
import os
import time
from datetime import datetime
from werkzeug.utils import secure_filename
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import WebDriverException
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import threading
import uuid

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['RESULTS_FOLDER'] = 'results'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create necessary folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)
os.makedirs('static', exist_ok=True)

# Store processing status
processing_status = {}

def click_element_safely(driver, element, element_name="element"):
    """Try multiple methods to click an element"""
    methods = [
        ("Regular click", lambda: element.click()),
        ("JavaScript click", lambda: driver.execute_script("arguments[0].click();", element)),
        ("ActionChains", lambda: ActionChains(driver).move_to_element(element).click().perform())
    ]
    
    for method_name, click_func in methods:
        try:
            click_func()
            return True
        except Exception:
            continue
    return False

def check_pan_aadhaar_status(driver, pan, aadhaar, entry_num, total_entries, is_first_entry):
    """Check status for a single PAN-Aadhaar combination"""
    result = {
        "entry_num": entry_num,
        "pan": pan,
        "aadhaar": aadhaar,
        "status": "Failed",
        "message": "",
        "link_status": "N/A",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    try:
        # Only click "Link Aadhaar" for the first entry
        if is_first_entry:
            link_element = None
            locators = [
                (By.XPATH, "//span[contains(text(), 'Link Aadhaar')]"),
                (By.XPATH, "//a[contains(text(), 'Link Aadhaar')]"),
                (By.XPATH, "//*[contains(text(), 'Link Aadhaar')]"),
            ]
            
            for locator in locators:
                try:
                    link_element = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable(locator)
                    )
                    break
                except:
                    continue
            
            if not link_element:
                result["message"] = "Could not find 'Link Aadhaar' button"
                return result
            
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link_element)
            time.sleep(1)
            
            if not click_element_safely(driver, link_element, "Link Aadhaar"):
                result["message"] = "Failed to click 'Link Aadhaar' button"
                return result
            
            time.sleep(2)
        else:
            time.sleep(1)
        
        # Enter PAN
        pan_input = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "mat-input-0"))
        )
        pan_input.clear()
        time.sleep(0.5)
        pan_input.send_keys(pan)
        time.sleep(1)
        
        # Enter Aadhaar
        aadhaar_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "mat-input-1"))
        )
        aadhaar_input.clear()
        time.sleep(0.5)
        aadhaar_input.send_keys(aadhaar)
        time.sleep(1)
        
        # Click Submit button
        submit_locators = [
            (By.XPATH, "//button[@type='submit' and @aria-label='View Link Aadhaar Status']"),
            (By.XPATH, "//button[@type='submit' and contains(text(), 'View Link Aadhaar Status')]"),
            (By.XPATH, "//button[contains(@class, 'large-button-primary') and contains(text(), 'View Link Aadhaar Status')]"),
        ]
        
        submit_button = None
        for locator in submit_locators:
            try:
                submit_button = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(locator)
                )
                break
            except:
                continue
        
        if not submit_button:
            result["message"] = "Submit button not found"
            return result
        
        WebDriverWait(driver, 10).until(lambda d: submit_button.is_enabled())
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", submit_button)
        time.sleep(1.5)
        
        if not click_element_safely(driver, submit_button, "Submit"):
            result["message"] = "Failed to click Submit button"
            return result
        
        # Wait for response message
        time.sleep(3)
        
        message_locators = [
            (By.XPATH, "//div[@role='alert']//span"),
            (By.XPATH, "//div[@aria-live='assertive']//span"),
            (By.XPATH, "//span[contains(text(), 'not linked')]"),
            (By.XPATH, "//span[contains(text(), 'already linked')]"),
            (By.XPATH, "//span[contains(text(), 'linked to given Aadhaar')]"),
        ]
        
        response_message = None
        for locator in message_locators:
            try:
                message_element = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located(locator)
                )
                response_message = message_element.text.strip()
                break
            except:
                continue
        
        # Fallback - search all spans
        if not response_message:
            all_spans = driver.find_elements(By.TAG_NAME, "span")
            for span in all_spans:
                text = span.text.strip()
                if text and ("PAN" in text or "Aadhaar" in text or "linked" in text):
                    response_message = text
                    break
        
        if response_message:
            result["message"] = response_message
            result["status"] = "Success"
            
            if "already linked" in response_message.lower():
                result["link_status"] = "Already Linked"
            elif "not linked" in response_message.lower():
                result["link_status"] = "Not Linked"
            elif "linked" in response_message.lower():
                result["link_status"] = "Linked"
            else:
                result["link_status"] = "Unknown"
        else:
            result["message"] = "Could not capture response message"
            result["link_status"] = "Unknown"
        
        # Click Close button
        time.sleep(1)
        close_locators = [
            (By.ID, "linkAadhaarFailureClose"),
            (By.XPATH, "//button[@id='linkAadhaarFailureClose']"),
            (By.XPATH, "//button[@aria-label='Close']"),
            (By.XPATH, "//button[contains(@class, 'primaryButton') and contains(text(), 'Close')]"),
        ]
        
        close_button = None
        for locator in close_locators:
            try:
                close_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(locator)
                )
                break
            except:
                continue
        
        if close_button:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", close_button)
            time.sleep(1)
            click_element_safely(driver, close_button, "Close")
            time.sleep(2)
        
    except Exception as e:
        result["message"] = f"Error: {str(e)}"
        result["status"] = "Failed"
    
    return result

def process_csv_file(job_id, csv_path):
    """Process CSV file in background"""
    try:
        processing_status[job_id] = {
            'status': 'processing',
            'progress': 0,
            'total': 0,
            'message': 'Initializing...'
        }
        
        # Read CSV
        df = pd.read_csv(csv_path)
        
        # Validate columns
        if 'PAN' not in df.columns or 'Aadhaar' not in df.columns:
            processing_status[job_id] = {
                'status': 'error',
                'message': 'CSV must contain PAN and Aadhaar columns'
            }
            return
        
        # Clean data
        df['PAN'] = df['PAN'].astype(str).str.strip().str.upper()
        df['Aadhaar'] = df['Aadhaar'].astype(str).str.strip()
        
        # Limit to 10 entries
        df = df.head(10)
        total_entries = len(df)
        
        processing_status[job_id]['total'] = total_entries
        processing_status[job_id]['message'] = 'Starting browser...'
        
        # Initialize browser (robust: try undetected_chromedriver first, then webdriver-manager fallback)
        def launch_chrome(headless=False):
            args = [
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-extensions',
                '--disable-blink-features=AutomationControlled',
            ]
            if headless:
                args.append('--headless=new')

            # Try undetected_chromedriver (preferred)
            try:
                uc_options = uc.ChromeOptions()
                for a in args:
                    uc_options.add_argument(a)
                uc_options.add_experimental_option("excludeSwitches", ["enable-automation"])
                uc_options.add_experimental_option('useAutomationExtension', False)
                return uc.Chrome(options=uc_options)
            except Exception:
                # Fallback: use webdriver-manager to install a matching chromedriver
                try:
                    chrome_options = webdriver.ChromeOptions()
                    for a in args:
                        chrome_options.add_argument(a)
                    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
                    chrome_options.add_experimental_option('useAutomationExtension', False)
                    driver_path = ChromeDriverManager().install()
                    service = Service(driver_path)
                    return webdriver.Chrome(service=service, options=chrome_options)
                except Exception as e:
                    raise RuntimeError(f"Failed to start Chrome (uc and fallback failed): {e}")

        # Initialize browser
        driver = launch_chrome(headless=False)
        results = []
        
        try:
            driver.get("https://www.incometax.gov.in/iec/foportal/")
            time.sleep(3)
            
            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            
            processing_status[job_id]['message'] = 'Processing entries...'
            
            # Process each row
            for idx, row in df.iterrows():
                pan = str(row['PAN'])
                aadhaar = str(row['Aadhaar'])
                entry_num = idx + 1
                
                processing_status[job_id]['progress'] = entry_num
                processing_status[job_id]['message'] = f'Processing {entry_num}/{total_entries}: {pan}'
                
                result = check_pan_aadhaar_status(
                    driver, pan, aadhaar, entry_num, total_entries, 
                    is_first_entry=(idx == 0)
                )
                results.append(result)
                
                if idx < total_entries - 1:
                    time.sleep(1)
            
            # Save results
            result_filename = f"result_{job_id}.csv"
            result_path = os.path.join(app.config['RESULTS_FOLDER'], result_filename)
            
            fieldnames = ["entry_num", "pan", "aadhaar", "status", "link_status", "message", "timestamp"]
            with open(result_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(results)
            
            processing_status[job_id] = {
                'status': 'completed',
                'progress': total_entries,
                'total': total_entries,
                'message': 'Processing completed!',
                'result_file': result_filename,
                'results': results
            }
            
        finally:
            driver.quit()
            
    except Exception as e:
        processing_status[job_id] = {
            'status': 'error',
            'message': f'Error: {str(e)}'
        }

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/download-template')
def download_template():
    template_path = os.path.join('static', 'pan_aadhaar_template.csv')
    return send_file(template_path, as_attachment=True, download_name='pan_aadhaar_template.csv')

@app.route('/process', methods=['POST'])
def process():
    if 'csv_file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['csv_file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'Only CSV files are allowed'}), 400
    
    # Save uploaded file
    filename = secure_filename(file.filename)
    job_id = str(uuid.uuid4())
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_{filename}")
    file.save(filepath)
    
    # Start processing in background thread
    thread = threading.Thread(target=process_csv_file, args=(job_id, filepath))
    thread.start()
    
    return jsonify({'job_id': job_id, 'message': 'Processing started'})

@app.route('/status/<job_id>')
def get_status(job_id):
    if job_id not in processing_status:
        return jsonify({'error': 'Job not found'}), 404
    
    return jsonify(processing_status[job_id])

@app.route('/download-result/<job_id>')
def download_result(job_id):
    if job_id not in processing_status:
        return jsonify({'error': 'Job not found'}), 404

    status = processing_status[job_id]
    if status.get('status') != 'completed':
        return jsonify({
            'error': 'Processing not completed',
            'status': status.get('status'),
            'progress': status.get('progress')
        }), 400

    result_file = status.get('result_file')
    if not result_file:
        return jsonify({'error': 'Result file not recorded for this job'}), 500

    result_path = os.path.join(app.config['RESULTS_FOLDER'], result_file)
    if not os.path.isfile(result_path):
        return jsonify({'error': 'Result file missing on server', 'expected_path': result_path}), 404

    try:
        return send_file(
            result_path,
            as_attachment=True,
            download_name=f'pan_aadhaar_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )
    except Exception as e:
        return jsonify({'error': 'Failed to send result file', 'message': str(e)}), 500


@app.route('/test-create-result/<job_id>', methods=['POST', 'GET'])
def test_create_result(job_id):
    """Create a dummy result CSV and mark the job completed (for testing download)."""
    os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)
    result_filename = f"result_{job_id}.csv"
    result_path = os.path.join(app.config['RESULTS_FOLDER'], result_filename)

    # Create a small dummy CSV
    try:
        with open(result_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["entry_num", "pan", "aadhaar", "status", "link_status", "message", "timestamp"])
            writer.writerow([1, "ABCDE1234F", "123412341234", "Success", "Linked", "Test entry", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])

        # Update processing_status to completed
        processing_status[job_id] = {
            'status': 'completed',
            'progress': 1,
            'total': 1,
            'message': 'Dummy result created for testing',
            'result_file': result_filename,
            'results': []
        }

        return jsonify({'message': 'Dummy result created', 'result_path': result_path}), 201
    except Exception as e:
        return jsonify({'error': 'Failed to create dummy result', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, threaded=True)