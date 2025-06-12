# app.py - Flask Web Application
from flask import Flask, render_template, request, jsonify
import pandas as pd
import numpy as np
import json
import requests
import io
import time
from datetime import datetime
import os

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Warehouse mapping configuration
WAREHOUSE_MAPPING = {
    'NJ9': {'zipcode': '07114', 'name': 'Newark, NJ', 'color': '#FF6B6B'},
    'NJ8': {'zipcode': '07201', 'name': 'Elizabeth, NJ', 'color': '#4ECDC4'},
    'NJ7': {'zipcode': '08817', 'name': 'Edison, NJ', 'color': '#45B7D1'},
    'NJ-Main': {'zipcode': '07306', 'name': 'Jersey City, NJ', 'color': '#96CEB4'},
    'TX8828': {'zipcode': '75261', 'name': 'Dallas, TX', 'color': '#FFEAA7'},
    'TX8829': {'zipcode': '76155', 'name': 'Fort Worth, TX', 'color': '#DDA0DD'},
    'TX-DFW': {'zipcode': '75063', 'name': 'Irving, TX', 'color': '#98D8C8'},
    'CA-LA': {'zipcode': '90058', 'name': 'Los Angeles, CA', 'color': '#F7DC6F'},
    'CA-SF': {'zipcode': '94080', 'name': 'South San Francisco, CA', 'color': '#BB8FCE'},
    'WNT485': {'zipcode': '90248', 'name': 'Gardena, CA', 'color': '#85C1E9'},
    'WNT486': {'zipcode': '91761', 'name': 'Ontario, CA', 'color': '#F8C471'},
    'WNT487': {'zipcode': '92408', 'name': 'San Bernardino, CA', 'color': '#82E0AA'},
    'IL-CHI': {'zipcode': '60638', 'name': 'Chicago, IL', 'color': '#D7BDE2'},
    'IL9': {'zipcode': '60106', 'name': 'Bensenville, IL', 'color': '#A9DFBF'},
    'GA-ATL': {'zipcode': '30349', 'name': 'Atlanta, GA', 'color': '#F9E79F'},
    'FL-MIA': {'zipcode': '33166', 'name': 'Miami, FL', 'color': '#AED6F1'},
    'Unknown': {'zipcode': '07114', 'name': 'Unknown Location', 'color': '#BDC3C7'}
}

# Global coordinate cache
coordinate_cache = {}

def get_warehouse_info(warehouse_name):
    """Get warehouse information with automatic fixing"""
    if not warehouse_name:
        return WAREHOUSE_MAPPING['Unknown']
    
    name = str(warehouse_name).strip()
    
    # Direct match
    if name in WAREHOUSE_MAPPING:
        return WAREHOUSE_MAPPING[name]
    
    # Fuzzy matching
    name_upper = name.upper()
    
    if name_upper.startswith('NJ'):
        return WAREHOUSE_MAPPING['NJ9']
    elif name_upper.startswith('TX'):
        return WAREHOUSE_MAPPING['TX8828']
    elif name_upper.startswith('CA') or 'LA' in name_upper:
        return WAREHOUSE_MAPPING['CA-LA']
    elif name_upper.startswith('WNT'):
        return WAREHOUSE_MAPPING['WNT485']
    elif name_upper.startswith('IL') or 'CHI' in name_upper:
        return WAREHOUSE_MAPPING['IL-CHI']
    elif 'NYC' in name_upper:
        return WAREHOUSE_MAPPING['NJ-Main']
    
    return WAREHOUSE_MAPPING['Unknown']

def extract_zipcode(zipcode_str):
    """Extract 5-digit zipcode from string"""
    if not zipcode_str:
        return None
    
    # Remove all non-digits and take first 5
    zipcode = ''.join(filter(str.isdigit, str(zipcode_str)))[:5]
    return zipcode if len(zipcode) == 5 else None

def get_coordinates(zipcode):
    """Get coordinates for zipcode with caching"""
    if zipcode in coordinate_cache:
        return coordinate_cache[zipcode]
    
    try:
        response = requests.get(f'http://api.zippopotam.us/us/{zipcode}', timeout=5)
        if response.status_code == 200:
            data = response.json()
            if 'places' in data and len(data['places']) > 0:
                place = data['places'][0]
                coords = {
                    'lat': float(place['latitude']),
                    'lng': float(place['longitude']),
                    'city': place['place name'],
                    'state': place['state abbreviation']
                }
                coordinate_cache[zipcode] = coords
                return coords
    except Exception as e:
        print(f"Error getting coordinates for {zipcode}: {e}")
    
    coordinate_cache[zipcode] = None
    return None

def calculate_distance(lat1, lng1, lat2, lng2):
    """Calculate distance between two points in km"""
    R = 6371  # Earth's radius in km
    
    lat1, lng1, lat2, lng2 = map(np.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng/2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
    
    return round(R * c)

def process_csv_data(csv_content):
    """Process uploaded CSV data"""
    try:
        # Read CSV
        df = pd.read_csv(io.StringIO(csv_content))
        
        # Limit to 500 records for performance
        original_count = len(df)
        df = df.head(500)
        
        processed_data = []
        
        for _, row in df.iterrows():
            try:
                # Parse date
                shipment_date = None
                if 'created_time' in row and pd.notna(row['created_time']):
                    date_str = str(row['created_time'])
                    if '/' in date_str:
                        try:
                            # Try parsing MM/DD/YY HH:MM format
                            parts = date_str.split(' ')[0].split('/')
                            if len(parts) == 3:
                                month = parts[0].zfill(2)
                                day = parts[1].zfill(2)
                                year = parts[2] if len(parts[2]) == 4 else '20' + parts[2]
                                shipment_date = f"{year}-{month}-{day}"
                        except:
                            shipment_date = '2024-03-15'  # Default
                
                # Fix warehouse zipcode
                warehouse_info = get_warehouse_info(row.get('warehouse_name'))
                
                # Extract destination zipcode
                dest_zipcode = extract_zipcode(row.get('shipto_postal_code'))
                
                if warehouse_info and dest_zipcode:
                    processed_data.append({
                        'id': row.get('id', len(processed_data) + 1),
                        'shipment_date': shipment_date or '2024-03-15',
                        'warehouse_name': row.get('warehouse_name', 'Unknown'),
                        'warehouse_zipcode': warehouse_info['zipcode'],
                        'warehouse_display': warehouse_info['name'],
                        'dest_zipcode': dest_zipcode,
                        'dest_city': row.get('shipto_city', 'Unknown'),
                        'dest_state': row.get('shipto_state', ''),
                        'carrier': row.get('carrier', 'Unknown'),
                        'business_type': row.get('biz_type', 'Standard'),
                        'weight_kg': float(row.get('gw', 1)) if pd.notna(row.get('gw')) else 1,
                        'volume_m3': float(row.get('vol', 0.1)) if pd.notna(row.get('vol')) else 0.1,
                        'packages': int(row.get('pkg_num', 1)) if pd.notna(row.get('pkg_num')) else 1
                    })
            except Exception as e:
                print(f"Error processing row: {e}")
                continue
        
        return processed_data, original_count
        
    except Exception as e:
        raise Exception(f"CSV processing failed: {str(e)}")

def enrich_with_coordinates(data):
    """Add coordinates to processed data"""
    # Get unique zipcodes
    unique_zipcodes = set()
    for item in data:
        unique_zipcodes.add(item['warehouse_zipcode'])
        unique_zipcodes.add(item['dest_zipcode'])
    
    # Get coordinates for all zipcodes
    for zipcode in unique_zipcodes:
        if zipcode not in coordinate_cache:
            get_coordinates(zipcode)
            time.sleep(0.1)  # Rate limiting
    
    # Add coordinates to data
    enriched_data = []
    for item in data:
        warehouse_coord = coordinate_cache.get(item['warehouse_zipcode'])
        dest_coord = coordinate_cache.get(item['dest_zipcode'])
        
        if warehouse_coord and dest_coord:
            item.update({
                'origin_lat': warehouse_coord['lat'],
                'origin_lng': warehouse_coord['lng'],
                'dest_lat': dest_coord['lat'],
                'dest_lng': dest_coord['lng'],
                'distance_km': calculate_distance(
                    warehouse_coord['lat'], warehouse_coord['lng'],
                    dest_coord['lat'], dest_coord['lng']
                )
            })
            enriched_data.append(item)
    
    return enriched_data

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def upload_csv():
    """Handle CSV file upload and processing"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.lower().endswith('.csv'):
            return jsonify({'error': 'Please upload a CSV file'}), 400
        
        # Read file content
        csv_content = file.read().decode('utf-8')
        
        # Process data
        processed_data, original_count = process_csv_data(csv_content)
        
        if not processed_data:
            return jsonify({'error': 'No valid data found in CSV'}), 400
        
        # Enrich with coordinates
        enriched_data = enrich_with_coordinates(processed_data)
        
        if not enriched_data:
            return jsonify({'error': 'Could not get coordinates for any locations'}), 400
        
        # Generate statistics
        stats = {
            'total_records': len(enriched_data),
            'original_count': original_count,
            'unique_warehouses': len(set(item['warehouse_name'] for item in enriched_data)),
            'unique_destinations': len(set(item['dest_city'] for item in enriched_data)),
            'total_distance': sum(item['distance_km'] for item in enriched_data),
            'date_range': {
                'start': min(item['shipment_date'] for item in enriched_data),
                'end': max(item['shipment_date'] for item in enriched_data)
            }
        }
        
        return jsonify({
            'success': True,
            'data': enriched_data,
            'stats': stats,
            'message': f'Successfully processed {len(enriched_data)} shipment records'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sample')
def download_sample():
    """Generate and return sample CSV data"""
    sample_data = """id,created_time,warehouse_name,shipto_postal_code,shipto_city,shipto_state,shipto_country_code,carrier,biz_type,gw,vol,pkg_num
1,3/15/24 10:30,NJ9,10001,New York,NY,US,FedEx,Express,2.5,0.01,1
2,3/15/24 11:45,TX8828,90210,Beverly Hills,CA,US,UPS,Standard,1.8,0.008,1
3,3/15/24 14:20,CA-LA,60601,Chicago,IL,US,DHL,Express,3.2,0.015,2
4,3/16/24 09:15,NJ8,33101,Miami,FL,US,FedEx,Standard,2.1,0.012,1
5,3/16/24 16:30,WNT485,98101,Seattle,WA,US,UPS,Express,4.5,0.025,3
6,3/17/24 08:45,IL-CHI,02101,Boston,MA,US,USPS,Standard,1.9,0.009,1
7,3/17/24 13:20,TX8829,30301,Atlanta,GA,US,DHL,Express,3.8,0.018,2
8,3/18/24 10:15,WNT486,75201,Dallas,TX,US,FedEx,Standard,2.7,0.013,1
9,3/18/24 15:40,CA-SF,80202,Denver,CO,US,UPS,Express,5.2,0.028,4
10,3/19/24 11:25,GA-ATL,85001,Phoenix,AZ,US,DHL,Standard,3.1,0.016,2
11,3/19/24 14:50,NJ7,19101,Philadelphia,PA,US,FedEx,Express,2.3,0.011,1
12,3/20/24 09:30,FL-MIA,37201,Nashville,TN,US,UPS,Standard,4.1,0.022,3
13,3/20/24 16:15,IL9,55401,Minneapolis,MN,US,USPS,Express,1.6,0.007,1
14,3/21/24 12:00,NJ9,97201,Portland,OR,US,DHL,Standard,3.5,0.017,2
15,3/21/24 17:30,TX8828,63101,St. Louis,MO,US,FedEx,Express,2.9,0.014,1"""
    
    from flask import Response
    return Response(
        sample_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=sample_express_parcel.csv'}
    )

@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'cache_size': len(coordinate_cache)
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)