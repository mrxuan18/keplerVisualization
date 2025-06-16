from flask import Flask, request, jsonify, render_template_string, send_file
import pandas as pd
import numpy as np
from keplergl import KeplerGl
import requests
import json
from datetime import datetime
import time
import warnings
import os
import tempfile
import io
warnings.filterwarnings('ignore')

app = Flask(__name__)

class WarehouseFixedVisualizer:
    def __init__(self):
        self.coordinate_cache = {}
        self.zipcode_api_base = "http://api.zippopotam.us/us/"
        self.all_data = None
        self.warehouse_mapping = None

    def get_warehouse_mapping(self):
        """获取warehouse邮编映射"""
        return {
            # NJ系列 - 新泽西州
            'NJ9': '07114',          # Newark, NJ
            'NJ8': '07201',          # Elizabeth, NJ
            'NJ7': '08817',          # Edison, NJ
            'NJ-Main': '07306',      # Jersey City, NJ
            
            # TX系列 - 德克萨斯州
            'TX8828': '75261',       # Dallas, TX
            'TX8829': '76155',       # Fort Worth, TX
            'TX-DFW': '75063',       # Irving, TX
            'TX-Houston': '77032',   # Houston, TX
            
            # WNT系列 - West Coast
            'WNT485': '90248',       # Gardena, CA
            'WNT486': '91761',       # Ontario, CA
            'WNT487': '92408',       # San Bernardino, CA
            
            # CA系列
            'CA-LA': '90058',        # Los Angeles, CA
            'CA-SF': '94080',        # South San Francisco, CA
            'CA-OAK': '94621',       # Oakland, CA
            
            # IL系列
            'IL-CHI': '60638',       # Chicago, IL
            'IL9': '60106',          # Bensenville, IL
            
            # GA系列
            'GA-ATL': '30349',       # Atlanta, GA
            
            # FL系列
            'FL-MIA': '33166',       # Miami, FL
            
            # 默认
            'Unknown': '07114',
            'MAIN': '10001',
            'NYC-Main': '11378',
        }

    def get_warehouse_zipcode(self, warehouse_name):
        """根据warehouse名称获取邮编"""
        if pd.isna(warehouse_name):
            return self.warehouse_mapping['Unknown']
        
        warehouse_name = str(warehouse_name).strip()
        
        # 直接匹配
        if warehouse_name in self.warehouse_mapping:
            return self.warehouse_mapping[warehouse_name]
        
        # 模糊匹配
        warehouse_upper = warehouse_name.upper()
        
        if warehouse_upper.startswith('NJ'):
            return self.warehouse_mapping['NJ9']
        elif warehouse_upper.startswith('TX'):
            return self.warehouse_mapping['TX8828']
        elif warehouse_upper.startswith('WNT'):
            return self.warehouse_mapping['WNT485']
        elif warehouse_upper.startswith('CA'):
            return self.warehouse_mapping['CA-LA']
        elif warehouse_upper.startswith('IL'):
            return self.warehouse_mapping['IL-CHI']
        elif 'NYC' in warehouse_upper or 'NEW YORK' in warehouse_upper:
            return self.warehouse_mapping['NYC-Main']
        elif 'DALLAS' in warehouse_upper or 'DFW' in warehouse_upper:
            return self.warehouse_mapping['TX-DFW']
        elif 'LA' in warehouse_upper or 'LOS ANGELES' in warehouse_upper:
            return self.warehouse_mapping['CA-LA']
        
        return self.warehouse_mapping['Unknown']

    def extract_zipcode(self, zipcode_str):
        """提取5位数邮编"""
        if pd.isna(zipcode_str):
            return None
        zipcode_str = str(zipcode_str).strip()
        zipcode = ''.join(filter(str.isdigit, zipcode_str))[:5]
        return zipcode if len(zipcode) == 5 else None

    def get_coordinates(self, zipcode):
        """获取邮编坐标"""
        if not zipcode or zipcode in self.coordinate_cache:
            return self.coordinate_cache.get(zipcode, (None, None))

        try:
            url = f"{self.zipcode_api_base}{zipcode}"
            response = requests.get(url, timeout=5)

            if response.status_code == 200:
                data = response.json()
                if 'places' in data and len(data['places']) > 0:
                    place = data['places'][0]
                    lat, lng = float(place['latitude']), float(place['longitude'])
                    self.coordinate_cache[zipcode] = (lat, lng)
                    print(f"   ✓ {zipcode}: {place['place name']}, {place['state abbreviation']}")
                    return (lat, lng)

            self.coordinate_cache[zipcode] = (None, None)
            return (None, None)

        except Exception as e:
            print(f"   ✗ {zipcode}: API请求失败")
            self.coordinate_cache[zipcode] = (None, None)
            return (None, None)

    def process_timestamp(self, timestamp_str):
        """处理时间戳"""
        if pd.isna(timestamp_str):
            return None, None

        try:
            if isinstance(timestamp_str, str) and '/' in timestamp_str:
                dt = datetime.strptime(timestamp_str, '%m/%d/%y %H:%M')
                return dt.strftime('%Y-%m-%d'), dt.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(timestamp_str, (int, float)):
                if timestamp_str > 1e10:
                    timestamp_str = timestamp_str / 1000
                dt = datetime.fromtimestamp(timestamp_str)
                return dt.strftime('%Y-%m-%d'), dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            pass
        return None, None

    def process_data(self, df, sample_size=500):
        """处理数据 - 基于Colab版本优化"""
        print(f"🔄 开始处理数据，样本大小: {sample_size}")
        
        # 初始化映射
        self.warehouse_mapping = self.get_warehouse_mapping()
        
        # 限制数据量
        df = df.head(sample_size)
        print(f"📂 原始数据: {len(df)} 行")

        # 修复warehouse邮编
        print("🔧 修复warehouse邮编...")
        df['fixed_warehouse_zipcode'] = df['warehouse_name'].apply(self.get_warehouse_zipcode)

        # 显示修复结果
        warehouse_fix_stats = df.groupby(['warehouse_name', 'fixed_warehouse_zipcode']).size().reset_index(name='count')
        print("📋 Warehouse邮编修复结果:")
        for _, row in warehouse_fix_stats.iterrows():
            print(f"   {row['warehouse_name']} → {row['fixed_warehouse_zipcode']} ({row['count']} 条记录)")

        # 处理时间戳
        print("⏰ 处理时间戳...")
        timestamp_results = df['created_time'].apply(self.process_timestamp)
        df['shipment_date'] = [r[0] for r in timestamp_results]
        df['shipment_datetime'] = [r[1] for r in timestamp_results]

        # 清洗目的地邮编
        print("📮 清洗目的地邮编...")
        df['destination_zipcode'] = df['shipto_postal_code'].apply(self.extract_zipcode)

        # 过滤有效数据
        valid_df = df[
            (df['shipment_date'].notna()) &
            (df['fixed_warehouse_zipcode'].notna()) &
            (df['destination_zipcode'].notna())
        ].copy()

        print(f"✅ 有效数据: {len(valid_df)} 行")

        if len(valid_df) == 0:
            print("❌ 没有有效数据!")
            return None

        # 显示日期分布
        date_counts = valid_df['shipment_date'].value_counts().sort_index()
        print(f"📅 日期分布 ({len(date_counts)} 天):")
        for date, count in date_counts.items():
            print(f"   {date}: {count} 笔")

        # 获取所有唯一邮编
        all_zipcodes = list(set(
            valid_df['fixed_warehouse_zipcode'].tolist() +
            valid_df['destination_zipcode'].tolist()
        ))

        print(f"🌍 获取 {len(all_zipcodes)} 个邮编的坐标...")
        
        successful_coords = 0
        for i, zipcode in enumerate(all_zipcodes):
            coord = self.get_coordinates(zipcode)
            if coord != (None, None):
                successful_coords += 1

            if (i + 1) % 10 == 0:
                print(f"   进度: {i + 1}/{len(all_zipcodes)} | 成功: {successful_coords}")
            time.sleep(0.1)  # 避免API限制

        success_rate = successful_coords / len(all_zipcodes) * 100
        print(f"✅ 坐标获取成功率: {successful_coords}/{len(all_zipcodes)} ({success_rate:.1f}%)")

        # 添加坐标
        print("📍 添加坐标信息...")
        valid_df['warehouse_lat'] = valid_df['fixed_warehouse_zipcode'].apply(
            lambda z: self.coordinate_cache.get(z, (None, None))[0]
        )
        valid_df['warehouse_lng'] = valid_df['fixed_warehouse_zipcode'].apply(
            lambda z: self.coordinate_cache.get(z, (None, None))[1]
        )
        valid_df['destination_lat'] = valid_df['destination_zipcode'].apply(
            lambda z: self.coordinate_cache.get(z, (None, None))[0]
        )
        valid_df['destination_lng'] = valid_df['destination_zipcode'].apply(
            lambda z: self.coordinate_cache.get(z, (None, None))[1]
        )

        # 最终过滤
        final_df = valid_df[
            (valid_df['warehouse_lat'].notna()) &
            (valid_df['destination_lat'].notna())
        ].copy()

        print(f"🎯 最终数据（含坐标）: {len(final_df)} 行")

        if len(final_df) == 0:
            print("❌ 没有数据包含有效坐标!")
            return None

        # 显示最终统计
        print(f"📊 最终统计:")
        final_warehouse_stats = final_df.groupby(['warehouse_name', 'fixed_warehouse_zipcode']).size().reset_index(name='count')
        print("仓库分布:")
        for _, row in final_warehouse_stats.iterrows():
            warehouse_coord = self.coordinate_cache.get(row['fixed_warehouse_zipcode'], (None, None))
            if warehouse_coord != (None, None):
                print(f"   {row['warehouse_name']} ({row['fixed_warehouse_zipcode']}): {row['count']} 笔 → 坐标: {warehouse_coord}")

        # 创建Kepler数据集
        print(f"📋 创建Kepler.gl数据集...")
        kepler_data = pd.DataFrame({
            'shipment_id': final_df['id'],
            'shipment_date': final_df['shipment_date'],
            'warehouse': final_df['warehouse_name'].fillna('Unknown'),
            'warehouse_zipcode': final_df['fixed_warehouse_zipcode'],
            'origin_lat': final_df['warehouse_lat'],
            'origin_lng': final_df['warehouse_lng'],
            'dest_lat': final_df['destination_lat'],
            'dest_lng': final_df['destination_lng'],
            'dest_zipcode': final_df['destination_zipcode'],
            'dest_city': final_df['shipto_city'].fillna('Unknown'),
            'dest_country': final_df['shipto_country_code'].fillna('US'),
            'carrier': final_df['carrier'].fillna('Unknown'),
            'business_type': final_df.get('biz_type', pd.Series(['Standard'] * len(final_df))).fillna('Standard'),
            'weight_kg': final_df.get('gw', pd.Series([1] * len(final_df))).fillna(1),
            'volume_m3': final_df.get('vol', pd.Series([0.1] * len(final_df))).fillna(0.1),
            'packages': final_df.get('pkg_num', pd.Series([1] * len(final_df))).fillna(1)
        })

        # 计算距离
        kepler_data['distance_km'] = np.sqrt(
            (kepler_data['dest_lat'] - kepler_data['origin_lat'])**2 +
            (kepler_data['dest_lng'] - kepler_data['origin_lng'])**2
        ) * 111

        self.all_data = kepler_data
        
        print(f"✅ Kepler数据集创建完成: {len(kepler_data)} 行")
        print(f"📅 包含日期: {kepler_data['shipment_date'].nunique()} 天")
        print(f"🏢 包含仓库: {kepler_data['warehouse'].nunique()} 个")
        print(f"📍 包含目的地: {kepler_data['dest_city'].nunique()} 个")

        return kepler_data

    def create_kepler_config_with_filters(self):
        """创建包含过滤器的Kepler配置 - 基于Colab版本"""
        return {
            'version': 'v1',
            'config': {
                'mapState': {
                    'latitude': 39.8,
                    'longitude': -95.0,
                    'zoom': 4,
                    'pitch': 0,
                    'bearing': 0
                },
                'visState': {
                    'filters': [
                        {
                            'dataId': ['shipments'],
                            'id': 'date_filter',
                            'name': ['shipment_date'],
                            'type': 'timeRange',
                            'value': [],
                            'enlarged': True,
                            'plotType': 'histogram',
                            'animationWindow': 'free'
                        }
                    ],
                    'layers': [
                        {
                            'id': 'arc_layer',
                            'type': 'arc',
                            'config': {
                                'dataId': 'shipments',
                                'label': 'Shipping Routes',
                                'color': [255, 0, 0],
                                'highlightColor': [252, 242, 26, 255],
                                'columns': {
                                    'lat0': 'origin_lat',
                                    'lng0': 'origin_lng',
                                    'lat1': 'dest_lat',
                                    'lng1': 'dest_lng'
                                },
                                'isVisible': True,
                                'visConfig': {
                                    'opacity': 0.8,
                                    'thickness': 2,
                                    'colorRange': {
                                        'name': 'Global Warming',
                                        'type': 'sequential',
                                        'category': 'Uber',
                                        'colors': ['#5A1846', '#900C3F', '#C70039', '#E3611C', '#F1920E', '#FFC300']
                                    },
                                    'sizeRange': [1, 8],
                                    'targetColor': [255, 0, 0]
                                }
                            }
                        },
                        {
                            'id': 'warehouse_points',
                            'type': 'point',
                            'config': {
                                'dataId': 'shipments',
                                'label': 'Warehouses',
                                'color': [0, 255, 0],
                                'columns': {
                                    'lat': 'origin_lat',
                                    'lng': 'origin_lng'
                                },
                                'isVisible': True,
                                'visConfig': {
                                    'opacity': 0.9,
                                    'radius': 15,
                                    'radiusRange': [10, 30]
                                }
                            }
                        },
                        {
                            'id': 'destination_points',
                            'type': 'point',
                            'config': {
                                'dataId': 'shipments',
                                'label': 'Destinations',
                                'color': [0, 100, 255],
                                'columns': {
                                    'lat': 'dest_lat',
                                    'lng': 'dest_lng'
                                },
                                'isVisible': True,
                                'visConfig': {
                                    'opacity': 0.8,
                                    'radius': 8,
                                    'radiusRange': [5, 20]
                                }
                            }
                        }
                    ]
                }
            }
        }

    def create_kepler_map(self):
        """创建Kepler.gl地图"""
        if self.all_data is None:
            return None

        print(f"🗺️ 创建包含所有数据的Kepler.gl地图...")
        print(f"📊 数据总量: {len(self.all_data)} 条运输记录")

        config = self.create_kepler_config_with_filters()
        map_instance = KeplerGl(height=700, width=1200, config=config)
        map_instance.add_data(data=self.all_data, name='shipments')
        
        return map_instance

# 全局可视化器实例
visualizer = WarehouseFixedVisualizer()

# HTML模板 - 纯前端，无依赖Kepler.gl库
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Express Parcel Visualization - Python Backend</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        
        .container {
            display: grid;
            grid-template-rows: auto 1fr;
            height: 100vh;
        }
        
        .header {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(15px);
            padding: 1.5rem 2rem;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            border-bottom: 3px solid #667eea;
        }
        
        .header h1 {
            color: #2d3748;
            font-size: 1.8rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .upload-section {
            display: flex;
            gap: 1rem;
            align-items: center;
            flex-wrap: wrap;
            margin-top: 1rem;
        }
        
        .upload-area {
            flex: 1;
            min-width: 300px;
            border: 2px dashed #cbd5e0;
            border-radius: 12px;
            padding: 1.5rem;
            text-align: center;
            cursor: pointer;
            background: rgba(255, 255, 255, 0.8);
            transition: all 0.3s ease;
        }
        
        .upload-area:hover {
            border-color: #667eea;
            background: rgba(255, 255, 255, 0.95);
            transform: translateY(-2px);
        }
        
        .upload-area.dragover {
            border-color: #667eea;
            background: rgba(102, 126, 234, 0.1);
        }
        
        .btn {
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            transition: all 0.3s ease;
        }
        
        .btn:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.3);
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }
        
        .btn-secondary {
            background: rgba(255,255,255,0.9);
            color: #4a5568;
            border: 1px solid #e2e8f0;
        }
        
        .main-content {
            background: white;
            overflow: hidden;
            position: relative;
        }
        
        .loading {
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            height: 100%;
            font-size: 1.2rem;
            color: #4a5568;
            text-align: center;
        }
        
        .loading-spinner {
            width: 60px;
            height: 60px;
            border: 4px solid #e2e8f0;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-bottom: 1rem;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .error-message, .success-message {
            padding: 1rem;
            border-radius: 8px;
            margin: 1rem 0;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            animation: fadeIn 0.5s ease-in;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .error-message {
            background: rgba(245, 101, 101, 0.1);
            border: 1px solid #f56565;
            color: #c53030;
        }
        
        .success-message {
            background: rgba(72, 187, 120, 0.1);
            border: 1px solid #48bb78;
            color: #2f855a;
        }
        
        .stats {
            display: flex;
            gap: 1rem;
            margin-top: 1rem;
            flex-wrap: wrap;
        }
        
        .stat-item {
            background: rgba(255, 255, 255, 0.2);
            backdrop-filter: blur(10px);
            padding: 0.5rem 1rem;
            border-radius: 8px;
            color: #2d3748;
            font-size: 0.85rem;
            font-weight: 600;
        }
        
        .feature-badge {
            background: linear-gradient(135deg, #48bb78, #38a169);
            color: white;
            padding: 0.3rem 0.8rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 700;
        }
        
        .status-indicator {
            background: rgba(72, 187, 120, 0.1);
            border: 1px solid #48bb78;
            color: #2f855a;
            padding: 0.75rem;
            border-radius: 8px;
            margin: 0.5rem 0;
            font-size: 0.9rem;
            text-align: center;
        }
        
        .kepler-map-container {
            width: 100%;
            height: 100%;
            border: none;
            background: white;
        }
        
        .ready-state {
            background: linear-gradient(135deg, #f7fafc, #edf2f7);
            border: 2px dashed #cbd5e0;
            border-radius: 12px;
            padding: 3rem;
            margin: 2rem;
            text-align: center;
            color: #4a5568;
        }
        
        .ready-state h3 {
            color: #2d3748;
            margin-bottom: 1rem;
            font-size: 1.5rem;
        }
        
        .feature-list {
            margin-top: 2rem;
            text-align: left;
            max-width: 500px;
            margin-left: auto;
            margin-right: auto;
        }
        
        .feature-list li {
            margin: 0.5rem 0;
            padding-left: 1.5rem;
            position: relative;
        }
        
        .feature-list li::before {
            content: "✓";
            position: absolute;
            left: 0;
            color: #48bb78;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                <div>
                    <h1>🗺️ Express Parcel Visualization</h1>
                    <p>Python Backend with KeplerGL - Warehouse Location Auto-Fixed</p>
                </div>
                <div class="feature-badge">Python Backend</div>
            </div>
            
            <div class="status-indicator">
                ✅ Ready to process your data - No browser dependencies required
            </div>
            
            <div class="upload-section">
                <div class="upload-area" id="uploadArea">
                    <div style="font-size: 2rem; color: #667eea; margin-bottom: 0.5rem;">📤</div>
                    <div><strong>Drop CSV file here or click to browse</strong></div>
                    <div style="font-size: 0.8rem; color: #718096; margin-top: 0.5rem;">
                        Automatically fixes warehouse locations based on ID patterns
                    </div>
                </div>
                
                <div style="display: flex; flex-direction: column; gap: 0.5rem;">
                    <button class="btn" onclick="triggerFileSelection()" id="uploadBtn">
                        📁 Select CSV File
                    </button>
                    <button class="btn btn-secondary" onclick="downloadSample()">
                        📄 Sample Data
                    </button>
                    <button class="btn btn-secondary" onclick="resetVisualization()" id="resetBtn" style="display: none;">
                        🔄 Reset
                    </button>
                </div>
            </div>
            
            <div id="stats" class="stats" style="display: none;"></div>
            <div id="messages"></div>
            
            <input type="file" id="fileInput" accept=".csv" style="display: none;">
        </header>

        <main class="main-content">
            <div id="mapContent" class="ready-state">
                <h3>🚀 Express Parcel Logistics Visualization</h3>
                <p>Upload your express_parcel.csv file to create an interactive map showing shipment flows from warehouses to destinations.</p>
                
                <ul class="feature-list">
                    <li>Automatic warehouse location fixing (NJ, TX, CA, WNT series)</li>
                    <li>Interactive arc visualization showing shipping routes</li>
                    <li>Date-based filtering and analysis</li>
                    <li>Carrier and business type breakdowns</li>
                    <li>Geographic coordinate geocoding</li>
                    <li>Real-time data processing and validation</li>
                </ul>
                
                <div style="margin-top: 2rem; font-size: 0.9rem; color: #718096;">
                    Uses Python KeplerGL backend - no browser library dependencies
                </div>
            </div>
        </main>
    </div>

    <script>
        // No library dependency checks - direct functionality
        
        function showMessage(message, type) {
            const messagesDiv = document.getElementById('messages');
            const messageDiv = document.createElement('div');
            messageDiv.className = type === 'error' ? 'error-message' : 'success-message';
            messageDiv.innerHTML = (type === 'error' ? '⚠️ ' : '✅ ') + message;
            messagesDiv.appendChild(messageDiv);
            setTimeout(() => messageDiv.remove(), 8000);
        }
        
        function updateStats(stats) {
            const statsDiv = document.getElementById('stats');
            statsDiv.innerHTML = \`
                <div class="stat-item">\${stats.total_records} Records</div>
                <div class="stat-item">\${stats.unique_warehouses} Warehouses</div>
                <div class="stat-item">\${stats.unique_destinations} Destinations</div>
                <div class="stat-item">\${stats.date_range}</div>
            \`;
            statsDiv.style.display = 'flex';
        }
        
        function showLoading(message, details) {
            const mapContent = document.getElementById('mapContent');
            mapContent.innerHTML = \`
                <div class="loading">
                    <div class="loading-spinner"></div>
                    \${message}<br>
                    <small>\${details}</small>
                </div>
            \`;
        }
        
        function triggerFileSelection() {
            console.log('triggerFileSelection called');
            const fileInput = document.getElementById('fileInput');
            console.log('fileInput element:', fileInput);
            if (fileInput) {
                fileInput.click();
                console.log('fileInput.click() called');
            } else {
                console.error('fileInput element not found');
            }
        }
        
        // 前端读取CSV文件
        function readCSVFile(file) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = function(e) {
                    try {
                        const csvText = e.target.result;
                        const lines = csvText.split('\n');
                        const headers = lines[0].split(',').map(h => h.trim().replace(/['"]/g, ''));
                        
                        const data = [];
                        for (let i = 1; i < lines.length; i++) {
                            if (lines[i].trim()) {
                                const values = parseCSVLine(lines[i]);
                                if (values.length === headers.length) {
                                    const row = {};
                                    headers.forEach((header, index) => {
                                        row[header] = values[index];
                                    });
                                    data.push(row);
                                }
                            }
                        }
                        
                        console.log('CSV parsed successfully:', data.length, 'rows');
                        resolve({ headers, data });
                    } catch (error) {
                        reject(error);
                    }
                };
                reader.onerror = reject;
                reader.readAsText(file);
            });
        }
        
        // 简单的CSV行解析（处理引号内的逗号）
        function parseCSVLine(line) {
            const result = [];
            let current = '';
            let inQuotes = false;
            
            for (let i = 0; i < line.length; i++) {
                const char = line[i];
                
                if (char === '"') {
                    inQuotes = !inQuotes;
                } else if (char === ',' && !inQuotes) {
                    result.push(current.trim().replace(/^["']|["']$/g, ''));
                    current = '';
                } else {
                    current += char;
                }
            }
            
            result.push(current.trim().replace(/^["']|["']$/g, ''));
            return result;
        }
        
        async function uploadFile() {
            console.log('uploadFile called');
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];
            
            if (!file) {
                showMessage('No file selected', 'error');
                return;
            }
            
            if (!file.name.toLowerCase().endsWith('.csv')) {
                showMessage('Please upload a CSV file', 'error');
                return;
            }
            
            console.log('Processing file:', file.name);
            
            // Disable upload button during processing
            document.getElementById('uploadBtn').disabled = true;
            
            showLoading('📖 Reading CSV file...', 'Parsing data in browser');
            
            try {
                // 前端读取CSV文件
                const csvData = await readCSVFile(file);
                console.log('CSV data:', csvData);
                
                showLoading('🔄 Processing data and fixing warehouse locations...', 'Sending data to Python backend for visualization');
                
                // 发送解析后的数据到后端
                const response = await fetch('/api/process-data', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        filename: file.name,
                        headers: csvData.headers,
                        data: csvData.data.slice(0, 500) // 限制前500行
                    })
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    if (result.html) {
                        document.getElementById('mapContent').innerHTML = result.html;
                        if (result.stats) {
                            updateStats(result.stats);
                        }
                        document.getElementById('resetBtn').style.display = 'block';
                        showMessage(\`Successfully processed \${result.stats?.total_records || 'unknown'} records with warehouse location fixes!\`, 'success');
                        
                        // Show additional info if provided
                        if (result.message) {
                            setTimeout(() => {
                                showMessage(result.message, 'success');
                            }, 1000);
                        }
                    } else {
                        throw new Error(result.error || 'No visualization generated');
                    }
                } else {
                    throw new Error(result.error || 'Server error');
                }
                
            } catch (error) {
                document.getElementById('mapContent').innerHTML = \`
                    <div class="loading">
                        ❌ Failed to create visualization<br>
                        <small>Error: \${error.message}</small><br>
                        <small>Please check your CSV format and try again</small>
                    </div>
                \`;
                showMessage('Processing failed: ' + error.message, 'error');
            } finally {
                // Re-enable upload button
                document.getElementById('uploadBtn').disabled = false;
            }
        }
        
        async function downloadSample() {
            try {
                showMessage('Generating sample CSV...', 'success');
                const response = await fetch('/api/sample');
                
                if (!response.ok) {
                    throw new Error('Failed to generate sample file');
                }
                
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'sample_express_parcel.csv';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
                showMessage('Sample CSV downloaded! Contains 20 records with warehouse location examples.', 'success');
            } catch (error) {
                showMessage('Failed to download sample data: ' + error.message, 'error');
            }
        }
        
        function resetVisualization() {
            // Reset file input
            document.getElementById('fileInput').value = '';
            
            // Hide stats and reset button
            document.getElementById('stats').style.display = 'none';
            document.getElementById('resetBtn').style.display = 'none';
            
            // Reset map content
            document.getElementById('mapContent').innerHTML = \`
                <div class="ready-state">
                    <h3>🚀 Express Parcel Logistics Visualization</h3>
                    <p>Upload your express_parcel.csv file to create an interactive map showing shipment flows from warehouses to destinations.</p>
                    
                    <ul class="feature-list">
                        <li>Automatic warehouse location fixing (NJ, TX, CA, WNT series)</li>
                        <li>Interactive arc visualization showing shipping routes</li>
                        <li>Date-based filtering and analysis</li>
                        <li>Carrier and business type breakdowns</li>
                        <li>Geographic coordinate geocoding</li>
                        <li>Real-time data processing and validation</li>
                    </ul>
                    
                    <div style="margin-top: 2rem; font-size: 0.9rem; color: #718096;">
                        Uses Python KeplerGL backend - no browser library dependencies
                    </div>
                </div>
            \`;
            
            // Clear messages
            document.getElementById('messages').innerHTML = '';
            
            showMessage('Ready for new visualization', 'success');
        }
        
        // File drag and drop functionality
        const uploadArea = document.getElementById('uploadArea');
        
        uploadArea.addEventListener('click', function() {
            console.log('Upload area clicked');
            const fileInput = document.getElementById('fileInput');
            if (fileInput) {
                fileInput.click();
                console.log('File input clicked via upload area');
            }
        });
        
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });
        
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });
        
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                const fileInput = document.getElementById('fileInput');
                fileInput.files = files;
                
                // Trigger the change event manually
                const event = new Event('change', { bubbles: true });
                fileInput.dispatchEvent(event);
                
                // Automatically process the file when dropped
                setTimeout(() => {
                    uploadFile();
                }, 500);
            }
        });
        
        // Page load handler
        document.addEventListener('DOMContentLoaded', function() {
            console.log('Express Parcel Visualization loaded - Python backend ready');
            
            // Test file input availability
            const fileInput = document.getElementById('fileInput');
            console.log('File input found:', !!fileInput);
            
            // Test button functionality
            const uploadBtn = document.getElementById('uploadBtn');
            console.log('Upload button found:', !!uploadBtn);
            
            // Ensure file input works
            if (fileInput) {
                fileInput.addEventListener('change', handleFileSelection);
                console.log('File input change listener added');
            }
            
            // Test click handler
            if (uploadBtn) {
                console.log('Upload button onclick:', uploadBtn.onclick);
            }
        });
        
        function handleFileSelection(e) {
            console.log('File selection changed');
            if (e.target.files.length > 0) {
                const file = e.target.files[0];
                console.log('File selected:', file.name);
                
                // 更新按钮文本和功能
                const uploadBtn = document.getElementById('uploadBtn');
                uploadBtn.innerHTML = '🔄 Process & Visualize';
                uploadBtn.onclick = uploadFile;
                
                // 显示选择的文件名
                showMessage(\`File selected: \${file.name}. Click "Process & Visualize" to continue.\`, 'success');
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/process-data', methods=['POST'])
def process_data():
    """处理前端发送的JSON数据"""
    try:
        # 获取JSON数据
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data received'}), 400
        
        filename = data.get('filename', 'unknown.csv')
        headers = data.get('headers', [])
        csv_data = data.get('data', [])
        
        print(f"📂 接收到数据处理请求: {filename}")
        print(f"📊 数据: {len(csv_data)} 行, {len(headers)} 列")
        print(f"📋 列名: {headers}")
        
        if not csv_data:
            return jsonify({'error': 'No data to process'}), 400
        
        # 将JSON数据转换为DataFrame
        try:
            df = pd.DataFrame(csv_data)
            print(f"✅ DataFrame创建成功: {len(df)} 行")
            
            # 检查必要的列
            required_columns = ['warehouse_name', 'created_time', 'shipto_postal_code']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                return jsonify({
                    'error': f'Missing required columns: {missing_columns}. Available columns: {list(df.columns)}'
                }), 400
            
        except Exception as e:
            print(f"❌ DataFrame创建失败: {e}")
            return jsonify({'error': f'Failed to create DataFrame: {str(e)}'}), 400
        
        # 处理数据（使用现有的处理逻辑）
        try:
            processed_data = visualizer.process_data(df, sample_size=500)
        except Exception as e:
            print(f"❌ 数据处理失败: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Data processing failed: {str(e)}'}), 500
        
        if processed_data is None:
            return jsonify({'error': 'No valid data found after processing. Please check your CSV format.'}), 400
        
        # 创建Kepler地图
        try:
            print("🗺️ 创建Kepler.gl地图...")
            map_instance = visualizer.create_kepler_map()
            
            if map_instance is None:
                return jsonify({'error': 'Failed to create map visualization'}), 500
            
            # 获取HTML
            map_html = map_instance._repr_html_()
            print("✅ 地图HTML生成成功")
            
        except Exception as e:
            print(f"❌ 地图创建失败: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Map creation failed: {str(e)}'}), 500
        
        # 统计信息
        stats = {
            'total_records': len(processed_data),
            'unique_warehouses': processed_data['warehouse'].nunique(),
            'unique_destinations': processed_data['dest_city'].nunique(),
            'date_range': f"{processed_data['shipment_date'].min()} → {processed_data['shipment_date'].max()}"
        }
        
        print(f"📊 统计信息: {stats}")
        
        return jsonify({
            'html': map_html,
            'stats': stats,
            'message': 'Data processed successfully using frontend CSV parsing + backend visualization'
        })
        
    except Exception as e:
        print(f"❌ 数据处理失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """保留原有的文件上传功能作为备用"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        print("📂 接收到文件上传请求（备用方式）")
        
        # 保存临时文件
        with tempfile.NamedTemporaryFile(mode='w+b', suffix='.csv', delete=False) as tmp_file:
            file.save(tmp_file.name)
            print(f"📁 文件已保存到临时位置: {tmp_file.name}")
            
            # 读取CSV
            try:
                df = pd.read_csv(tmp_file.name)
                print(f"📊 成功读取CSV: {len(df)} 行, {len(df.columns)} 列")
                print(f"📋 列名: {list(df.columns)}")
            except Exception as e:
                return jsonify({'error': f'Failed to read CSV file: {str(e)}'}), 400
            
            # 处理数据
            try:
                processed_data = visualizer.process_data(df, sample_size=500)
            except Exception as e:
                print(f"❌ 数据处理失败: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': f'Data processing failed: {str(e)}'}), 500
            
            if processed_data is None:
                return jsonify({'error': 'No valid data found after processing. Please check your CSV format.'}), 400
            
            # 创建Kepler地图
            try:
                print("🗺️ 创建Kepler.gl地图...")
                map_instance = visualizer.create_kepler_map()
                
                if map_instance is None:
                    return jsonify({'error': 'Failed to create map visualization'}), 500
                
                # 获取HTML
                map_html = map_instance._repr_html_()
                print("✅ 地图HTML生成成功")
                
            except Exception as e:
                print(f"❌ 地图创建失败: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': f'Map creation failed: {str(e)}'}), 500
            
            # 统计信息
            stats = {
                'total_records': len(processed_data),
                'unique_warehouses': processed_data['warehouse'].nunique(),
                'unique_destinations': processed_data['dest_city'].nunique(),
                'date_range': f"{processed_data['shipment_date'].min()} → {processed_data['shipment_date'].max()}"
            }
            
            print(f"📊 统计信息: {stats}")
            
            # 清理临时文件
            try:
                os.unlink(tmp_file.name)
                print("🗑️ 临时文件已清理")
            except:
                pass
            
            return jsonify({
                'html': map_html,
                'stats': stats,
                'message': 'Warehouse locations automatically fixed based on ID patterns'
            })
            
    except Exception as e:
        print(f"❌ 上传处理失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Upload processing failed: {str(e)}'}), 500

@app.route('/api/sample')
def download_sample():
    """生成并下载样本CSV文件"""
    try:
        # 创建样本数据 - 基于真实的express_parcel格式
        sample_data = {
            'id': range(1, 21),
            'warehouse_name': [
                'NJ9', 'TX8828', 'CA-LA', 'NJ8', 'WNT485',
                'IL-CHI', 'TX-DFW', 'CA-SF', 'NJ7', 'WNT486',
                'GA-ATL', 'FL-MIA', 'CA-OAK', 'TX8829', 'IL9',
                'NYC-Main', 'NJ-Main', 'WNT487', 'TX-Houston', 'CA-LA'
            ],
            'created_time': [
                '1/15/24 10:30', '1/15/24 11:45', '1/16/24 09:15', '1/16/24 14:20', '1/17/24 16:10',
                '1/17/24 08:45', '1/18/24 13:20', '1/18/24 15:30', '1/19/24 11:15', '1/19/24 17:45',
                '1/20/24 09:30', '1/20/24 12:15', '1/21/24 10:45', '1/21/24 16:30', '1/22/24 14:15',
                '1/22/24 11:00', '1/23/24 13:45', '1/23/24 15:15', '1/24/24 09:45', '1/24/24 17:30'
            ],
            'shipto_postal_code': [
                '10001', '90210', '60601', '33101', '98101',
                '30309', '02101', '19102', '80202', '85001',
                '89101', '37201', '28201', '23219', '46201',
                '55401', '53201', '40201', '70112', '84101'
            ],
            'shipto_city': [
                'New York', 'Beverly Hills', 'Chicago', 'Miami', 'Seattle',
                'Atlanta', 'Boston', 'Philadelphia', 'Denver', 'Phoenix',
                'Las Vegas', 'Nashville', 'Charlotte', 'Richmond', 'Indianapolis',
                'Minneapolis', 'Milwaukee', 'Louisville', 'New Orleans', 'Salt Lake City'
            ],
            'shipto_country_code': ['US'] * 20,
            'carrier': [
                'FedEx', 'UPS', 'DHL', 'USPS', 'Amazon',
                'FedEx', 'UPS', 'DHL', 'USPS', 'Amazon',
                'FedEx', 'UPS', 'DHL', 'USPS', 'Amazon',
                'FedEx', 'UPS', 'DHL', 'USPS', 'Amazon'
            ],
            'biz_type': [
                'Express', 'Standard', 'Economy', 'Express', 'Standard',
                'Economy', 'Express', 'Standard', 'Economy', 'Express',
                'Standard', 'Economy', 'Express', 'Standard', 'Economy',
                'Express', 'Standard', 'Economy', 'Express', 'Standard'
            ],
            'gw': [1.5, 2.3, 0.8, 3.2, 1.1, 2.8, 1.9, 0.5, 4.1, 2.6, 
                   1.8, 3.5, 0.9, 2.4, 1.7, 3.8, 2.1, 1.3, 4.5, 2.9],
            'vol': [0.05, 0.12, 0.03, 0.18, 0.06, 0.15, 0.08, 0.02, 0.25, 0.14,
                    0.09, 0.22, 0.04, 0.13, 0.07, 0.28, 0.11, 0.05, 0.31, 0.16],
            'pkg_num': [1, 1, 2, 1, 3, 1, 2, 1, 1, 2, 
                       1, 1, 3, 1, 2, 1, 1, 2, 1, 3]
        }
        
        sample_df = pd.DataFrame(sample_data)
        
        # 创建CSV字符串
        csv_buffer = io.StringIO()
        sample_df.to_csv(csv_buffer, index=False)
        csv_content = csv_buffer.getvalue()
        
        # 创建响应
        response = app.response_class(
            csv_content,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=sample_express_parcel.csv'}
        )
        
        print("📄 样本CSV文件生成成功")
        return response
        
    except Exception as e:
        print(f"❌ 样本文件生成失败: {e}")
        return jsonify({'error': f'Failed to generate sample file: {str(e)}'}), 500

@app.route('/health')
def health_check():
    """健康检查端点"""
    return jsonify({
        'status': 'healthy',
        'service': 'Express Parcel Visualization',
        'version': '1.0.0',
        'features': ['warehouse_location_fix', 'kepler_visualization', 'zipcode_geocoding']
    })

if __name__ == '__main__':
    print("🚀 启动 Express Parcel Visualization 服务器")
    print("📍 Warehouse位置自动修复功能已启用")
    print("🗺️ 使用Python KeplerGL后端渲染")
    print("=" * 60)
    print("🔧 特性:")
    print("   • 自动修复warehouse邮编（基于ID模式）")
    print("   • 智能地理编码（API + 缓存）")
    print("   • 交互式Kepler.gl可视化")
    print("   • 数据清洗和验证")
    print("   • 响应式Web界面")
    print("=" * 60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)