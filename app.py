from flask import Flask, request, jsonify, render_template
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

    def analyze_warehouse_ids(self, df_sample):
        """分析文件中的warehouse ID并推测地理位置"""
        print("🔍 分析warehouse ID并推测地理位置...")
        
        warehouse_counts = df_sample['warehouse_name'].value_counts()
        print(f"📊 前{len(df_sample)}行中发现的warehouse:")
        for warehouse, count in warehouse_counts.items():
            print(f"   {warehouse}: {count} 次")

        # 根据warehouse ID推测地理位置和邮编
        warehouse_zipcode_mapping = {
            # NJ系列 - 新泽西州 (Newark, Elizabeth等物流中心)
            'NJ9': '07114',          # Newark, NJ - 主要物流中心
            'NJ8': '07201',          # Elizabeth, NJ - 港口物流中心
            'NJ7': '08817',          # Edison, NJ - 仓储区
            'NJ-Main': '07306',      # Jersey City, NJ

            # TX系列 - 德克萨斯州 (达拉斯-沃斯堡地区)
            'TX8828': '75261',       # Dallas, TX - 主要物流枢纽
            'TX8829': '76155',       # Fort Worth, TX
            'TX-DFW': '75063',       # Irving, TX - DFW机场附近
            'TX-Houston': '77032',   # Houston, TX - 船运中心

            # WNT系列 - 推测为West Coast + NT (Northwest Terminal)
            'WNT485': '90248',       # Gardena, CA - 洛杉矶地区物流中心
            'WNT486': '91761',       # Ontario, CA - 内陆帝国物流区
            'WNT487': '92408',       # San Bernardino, CA

            # CA系列 - 加利福尼亚州
            'CA-LA': '90058',        # Los Angeles, CA - 工业区
            'CA-SF': '94080',        # South San Francisco, CA
            'CA-OAK': '94621',       # Oakland, CA - 港口区

            # IL系列 - 伊利诺伊州 (芝加哥地区)
            'IL-CHI': '60638',       # Chicago, IL - 物流区
            'IL9': '60106',          # Bensenville, IL - O'Hare附近

            # GA系列 - 佐治亚州 (亚特兰大)
            'GA-ATL': '30349',       # Atlanta, GA - 机场物流区

            # FL系列 - 佛罗里达州 (迈阿密)
            'FL-MIA': '33166',       # Miami, FL - 物流中心

            # 通用/未知仓库 - 默认为主要物流中心
            'Unknown': '07114',      # 默认新泽西Newark
            'MAIN': '10001',         # 纽约主仓
            'NYC-Main': '11378',     # Queens, NY - 物流区
        }

        print(f"\n📍 Warehouse邮编映射表:")
        for warehouse, zipcode in warehouse_zipcode_mapping.items():
            print(f"   {warehouse} → {zipcode}")

        return warehouse_zipcode_mapping

    def get_warehouse_zipcode(self, warehouse_name):
        """根据warehouse名称获取对应邮编"""
        if pd.isna(warehouse_name):
            return self.warehouse_mapping['Unknown']

        warehouse_name = str(warehouse_name).strip()

        # 直接匹配
        if warehouse_name in self.warehouse_mapping:
            return self.warehouse_mapping[warehouse_name]

        # 模糊匹配
        warehouse_upper = warehouse_name.upper()

        # NJ系列匹配
        if warehouse_upper.startswith('NJ'):
            return self.warehouse_mapping.get('NJ9', '07114')

        # TX系列匹配
        elif warehouse_upper.startswith('TX'):
            return self.warehouse_mapping.get('TX8828', '75261')

        # WNT系列匹配
        elif warehouse_upper.startswith('WNT'):
            return self.warehouse_mapping.get('WNT485', '90248')

        # CA系列匹配
        elif warehouse_upper.startswith('CA'):
            return self.warehouse_mapping.get('CA-LA', '90058')

        # IL系列匹配
        elif warehouse_upper.startswith('IL'):
            return self.warehouse_mapping.get('IL-CHI', '60638')

        # 包含关键词匹配
        elif 'NYC' in warehouse_upper or 'NEW YORK' in warehouse_upper:
            return self.warehouse_mapping.get('NYC-Main', '11378')
        elif 'DALLAS' in warehouse_upper or 'DFW' in warehouse_upper:
            return self.warehouse_mapping.get('TX-DFW', '75063')
        elif 'LA' in warehouse_upper or 'LOS ANGELES' in warehouse_upper:
            return self.warehouse_mapping.get('CA-LA', '90058')
        elif 'CHICAGO' in warehouse_upper:
            return self.warehouse_mapping.get('IL-CHI', '60638')
        elif 'ATLANTA' in warehouse_upper:
            return self.warehouse_mapping.get('GA-ATL', '30349')
        elif 'MIAMI' in warehouse_upper:
            return self.warehouse_mapping.get('FL-MIA', '33166')

        # 默认返回
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
                    city = place['place name']
                    state = place['state abbreviation']
                    self.coordinate_cache[zipcode] = (lat, lng)
                    print(f"   ✓ {zipcode}: {city}, {state}")
                    return (lat, lng)

            self.coordinate_cache[zipcode] = (None, None)
            return (None, None)

        except Exception as e:
            print(f"   ✗ {zipcode}: API请求失败")
            self.coordinate_cache[zipcode] = (None, None)
            return (None, None)

    def process_timestamp(self, timestamp_str):
        """处理时间戳为标准格式"""
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
        """处理所有数据，修复warehouse邮编 - 完整Colab版本逻辑"""
        print(f"🔄 开始处理数据并修复warehouse邮编 (样本大小: {sample_size})...")

        # 1. 分析并创建warehouse映射
        df_sample = df.head(200)  # 先取200行分析warehouse
        self.warehouse_mapping = self.analyze_warehouse_ids(df_sample)

        # 2. 读取数据
        df = df.head(sample_size)
        print(f"\n📂 原始数据: {len(df)} 行")

        # 3. 修复warehouse邮编
        print("🔧 修复warehouse邮编...")
        df['fixed_warehouse_zipcode'] = df['warehouse_name'].apply(self.get_warehouse_zipcode)

        # 显示修复结果
        warehouse_fix_stats = df.groupby(['warehouse_name', 'fixed_warehouse_zipcode']).size().reset_index(name='count')
        print("📋 Warehouse邮编修复结果:")
        for _, row in warehouse_fix_stats.iterrows():
            print(f"   {row['warehouse_name']} → {row['fixed_warehouse_zipcode']} ({row['count']} 条记录)")

        # 4. 处理时间戳
        print("\n⏰ 处理时间戳...")
        timestamp_results = df['created_time'].apply(self.process_timestamp)
        df['shipment_date'] = [r[0] for r in timestamp_results]
        df['shipment_datetime'] = [r[1] for r in timestamp_results]

        # 5. 清洗目的地邮编
        print("📮 清洗目的地邮编...")
        df['destination_zipcode'] = df['shipto_postal_code'].apply(self.extract_zipcode)

        # 6. 过滤有效数据
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

        # 7. 获取所有邮编的坐标
        print(f"\n🌍 获取邮编坐标...")
        all_zipcodes = list(set(
            valid_df['fixed_warehouse_zipcode'].tolist() +
            valid_df['destination_zipcode'].tolist()
        ))

        print(f"需要处理 {len(all_zipcodes)} 个唯一邮编")

        successful_coords = 0
        for i, zipcode in enumerate(all_zipcodes):
            coord = self.get_coordinates(zipcode)
            if coord != (None, None):
                successful_coords += 1

            if (i + 1) % 10 == 0:
                print(f"   进度: {i + 1}/{len(all_zipcodes)} | 成功: {successful_coords}")
            time.sleep(0.1)

        success_rate = successful_coords / len(all_zipcodes) * 100
        print(f"✅ 坐标获取成功率: {successful_coords}/{len(all_zipcodes)} ({success_rate:.1f}%)")

        # 8. 添加坐标
        print("📍 添加坐标信息...")

        def get_lat(zipcode):
            coord = self.coordinate_cache.get(zipcode, (None, None))
            return coord[0] if coord and len(coord) == 2 else None

        def get_lng(zipcode):
            coord = self.coordinate_cache.get(zipcode, (None, None))
            return coord[1] if coord and len(coord) == 2 else None

        valid_df['warehouse_lat'] = valid_df['fixed_warehouse_zipcode'].apply(get_lat)
        valid_df['warehouse_lng'] = valid_df['fixed_warehouse_zipcode'].apply(get_lng)
        valid_df['destination_lat'] = valid_df['destination_zipcode'].apply(get_lat)
        valid_df['destination_lng'] = valid_df['destination_zipcode'].apply(get_lng)

        # 9. 最终过滤（必须有坐标）
        final_df = valid_df[
            (valid_df['warehouse_lat'].notna()) &
            (valid_df['destination_lat'].notna())
        ].copy()

        print(f"🎯 最终数据（含坐标）: {len(final_df)} 行")

        if len(final_df) == 0:
            print("❌ 没有数据包含有效坐标!")
            return None

        # 显示最终统计
        print(f"\n📊 最终统计:")
        final_warehouse_stats = final_df.groupby(['warehouse_name', 'fixed_warehouse_zipcode']).size().reset_index(name='count')
        print("仓库分布:")
        for _, row in final_warehouse_stats.iterrows():
            warehouse_coord = self.coordinate_cache.get(row['fixed_warehouse_zipcode'], (None, None))
            if warehouse_coord != (None, None):
                print(f"   {row['warehouse_name']} ({row['fixed_warehouse_zipcode']}): {row['count']} 笔 → 坐标: {warehouse_coord}")

        final_date_counts = final_df['shipment_date'].value_counts().sort_index()
        print("日期分布:")
        for date, count in final_date_counts.items():
            print(f"   {date}: {count} 笔")

        # 10. 创建Kepler数据集
        print(f"\n📋 创建Kepler.gl数据集...")

        kepler_data = pd.DataFrame({
            # 基本信息
            'shipment_id': final_df['id'],
            'shipment_date': final_df['shipment_date'],
            'shipment_datetime': final_df['shipment_datetime'],
            'warehouse': final_df['warehouse_name'].fillna('Unknown'),
            'warehouse_zipcode': final_df['fixed_warehouse_zipcode'],

            # 坐标信息
            'origin_lat': final_df['warehouse_lat'],
            'origin_lng': final_df['warehouse_lng'],
            'dest_lat': final_df['destination_lat'],
            'dest_lng': final_df['destination_lng'],

            # 地址信息
            'dest_zipcode': final_df['destination_zipcode'],
            'dest_city': final_df['shipto_city'].fillna('Unknown'),
            'dest_country': final_df['shipto_country_code'].fillna('US'),

            # 业务信息
            'carrier': final_df['carrier'].fillna('Unknown'),
            'business_type': final_df.get('biz_type', pd.Series(['Standard'] * len(final_df))).fillna('Standard'),
            'weight_kg': final_df.get('gw', pd.Series([1] * len(final_df))).fillna(1),
            'volume_m3': final_df.get('vol', pd.Series([0.1] * len(final_df))).fillna(0.1),
            'packages': final_df.get('pkg_num', pd.Series([1] * len(final_df))).fillna(1)
        })

        # 添加计算字段
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

        return kepler_data

    def create_kepler_config_with_filters(self):
        """创建包含过滤器的Kepler配置 - 完整Colab版本"""
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
        """创建包含所有数据的Kepler.gl地图 - 完整Colab版本"""
        if self.all_data is None:
            return None

        print(f"🗺️ 创建包含所有数据的Kepler.gl地图...")
        print(f"📊 数据总量: {len(self.all_data)} 条运输记录")

        # 显示warehouse分布
        warehouse_stats = self.all_data.groupby(['warehouse', 'warehouse_zipcode']).size().reset_index(name='count')
        print(f"\n🏢 仓库分布:")
        for _, row in warehouse_stats.iterrows():
            print(f"   {row['warehouse']} ({row['warehouse_zipcode']}): {row['count']} 笔")

        # 创建地图
        config = self.create_kepler_config_with_filters()
        map_instance = KeplerGl(height=700, width=1200, config=config)
        map_instance.add_data(data=self.all_data, name='shipments')

        print(f"\n✅ 地图创建完成!")
        print(f"🎛️ 使用方法:")
        print(f"   1. 地图显示所有仓库到目的地的运输路线")
        print(f"   2. 绿色圆点 = 仓库位置（基于修复的邮编）")
        print(f"   3. 蓝色圆点 = 目的地位置")
        print(f"   4. 红色弧线 = 运输路线")
        print(f"   5. 点击 'Filters' 添加日期、仓库、承运商等过滤器")

        return map_instance

# 全局可视化器实例
visualizer = WarehouseFixedVisualizer()

@app.route('/')
def index():
    return render_template('index.html')

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
        
        # 将JSON数据转换为DataFrame - 添加数据清洗
        try:
            # 清洗数据，确保所有值都是可序列化的
            cleaned_data = []
            for row in csv_data:
                cleaned_row = {}
                for key, value in row.items():
                    # 处理各种数据类型
                    if isinstance(value, bytes):
                        cleaned_row[key] = value.decode('utf-8', errors='ignore')
                    elif value is None:
                        cleaned_row[key] = ''
                    elif isinstance(value, (int, float, str, bool)):
                        cleaned_row[key] = value
                    else:
                        # 将其他类型转换为字符串
                        cleaned_row[key] = str(value)
                cleaned_data.append(cleaned_row)
            
            df = pd.DataFrame(cleaned_data)
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
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Failed to create DataFrame: {str(e)}'}), 400
        
        # 处理数据
        try:
            processed_data = visualizer.process_data(df, sample_size=100)
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
        
        # 统计信息 - 确保所有值都是可序列化的
        try:
            stats = {
                'total_records': int(len(processed_data)),
                'unique_warehouses': int(processed_data['warehouse'].nunique()),
                'unique_destinations': int(processed_data['dest_city'].nunique()),
                'date_range': f"{str(processed_data['shipment_date'].min())} → {str(processed_data['shipment_date'].max())}"
            }
            
            print(f"📊 统计信息: {stats}")
            
        except Exception as e:
            print(f"❌ 统计信息生成失败: {e}")
            stats = {
                'total_records': len(processed_data),
                'unique_warehouses': 0,
                'unique_destinations': 0,
                'date_range': 'Unknown'
            }
        
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
                processed_data = visualizer.process_data(df, sample_size=200)
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
        'version': '2.0.0',
        'architecture': 'frontend_csv_parsing + backend_visualization',
        'features': [
            'frontend_csv_parsing', 
            'warehouse_location_fix', 
            'kepler_visualization', 
            'zipcode_geocoding',
            'hybrid_architecture'
        ]
    })

if __name__ == '__main__':
    print("🚀 启动 Express Parcel Visualization 服务器")
    print("🏗️ 完整Colab逻辑集成：前端CSV解析 + 后端warehouse修复")
    print("📍 Warehouse位置自动修复功能已启用（完整版）")
    print("🗺️ 使用Python KeplerGL后端渲染")
    print("=" * 70)
    print("🔧 特性（基于成熟Colab版本）:")
    print("   • 前端CSV文件读取和解析（无上传限制）")
    print("   • 智能warehouse ID分析和邮编推测")
    print("   • 自动修复warehouse邮编（基于ID模式匹配）")
    print("   • 详细的数据处理步骤和日志")
    print("   • 智能地理编码（API + 缓存）")
    print("   • 完整的数据清洗和验证流水线")
    print("   • 交互式Kepler.gl可视化（多图层）")
    print("   • 时间序列过滤器和动画")
    print("   • 响应式Web界面 + 调试面板")
    print("=" * 70)
    print("📋 支持的Warehouse系列:")
    print("   • NJ系列: NJ9, NJ8, NJ7, NJ-Main (新泽西物流中心)")
    print("   • TX系列: TX8828, TX8829, TX-DFW, TX-Houston (德州枢纽)")
    print("   • WNT系列: WNT485, WNT486, WNT487 (西海岸终端)")
    print("   • CA系列: CA-LA, CA-SF, CA-OAK (加州港口)")
    print("   • IL, GA, FL系列: 芝加哥、亚特兰大、迈阿密")
    print("=" * 70)
    
    app.run(debug=True, host='0.0.0.0', port=5000)