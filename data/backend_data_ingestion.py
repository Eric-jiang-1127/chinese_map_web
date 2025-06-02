# backend_data_ingestion.py (修正版 v5)
import sqlite3
import requests
import json
import time

# CNKGraph API 基础 URL
CNKGRAPH_API_BASE = "https://api.cnkgraph.com"
DB_NAME = "hanmo_yutu.db"

# --- SSL 错误处理选项 ---
# 警告: 禁用SSL验证会带来安全风险。仅在完全信任服务器且了解风险的情况下用于调试。
# 如果持续遇到SSLError，并且您理解相关风险，可以尝试将下面一行改为 VERIFY_SSL = False
VERIFY_SSL = True # 默认为True，进行SSL验证

if not VERIFY_SSL:
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        print("警告: SSL验证已禁用。这仅应用于受信任的测试环境。")
    except ImportError:
        print("警告: urllib3 未安装，无法禁用 InsecureRequestWarning。SSL验证仍被禁用。")


def init_db():
    """初始化数据库和表结构"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historical_places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            k_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            dynasty TEXT,
            summary TEXT,
            details TEXT,
            latitude REAL,
            longitude REAL,
            raw_cnkg_data TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    print("数据库初始化完成。")

def get_region_details_and_coords(region_id):
    """根据 region_id 从 /api/map/region/{regionId} 获取坐标和可能的详细信息"""
    region_id_str = str(region_id) 
    latitude, longitude, summary_from_detail = None, None, None 

    try:
        detail_api_url = f"{CNKGRAPH_API_BASE}/api/map/region/{region_id_str}"
        print(f"    > 正在获取区域详情: {detail_api_url}")
        response = requests.get(detail_api_url, timeout=10, verify=VERIFY_SSL)
        response.raise_for_status() 
        detail_data_root = response.json()

        data_node = detail_data_root.get("data", detail_data_root)

        if not isinstance(data_node, dict): 
            print(f"    > 信息: Region ID {region_id_str} 的详情数据节点 (data_node) 不是预期的字典类型 (实际类型: {type(data_node)}). 这对于顶层区域可能是正常的，它可能返回子区域列表。DataNode (部分): {str(data_node)[:200]}")
            # 对于返回列表的情况，我们不认为这是此 region_id 本身的坐标信息源
            return None, None, "子区域列表" # 返回一个指示性的摘要

        latitude = data_node.get("Latitude", data_node.get("latitude"))
        longitude = data_node.get("Longitude", data_node.get("longitude"))
        
        summary_from_detail = data_node.get("Description", 
                                    data_node.get("description", 
                                    data_node.get("Name", 
                                    data_node.get("name", "无摘要"))))

        if not (isinstance(latitude, (int, float)) and isinstance(longitude, (int, float))):
            center = data_node.get("center")
            if isinstance(center, list) and len(center) == 2:
                if isinstance(center[1], (int, float)) and isinstance(center[0], (int, float)):
                    latitude = center[1]
                    longitude = center[0]
                    print(f"    > 信息: Region ID {region_id_str} 从 'center' 列表获取到坐标 ([Lng, Lat] -> Lat, Lng): ({latitude}, {longitude})。")
            elif isinstance(center, dict):
                lat_c = center.get("lat", center.get("Lat", center.get("Latitude")))
                lng_c = center.get("lng", center.get("Lng", center.get("Longitude", center.get("lon"))))
                if isinstance(lat_c, (int, float)) and isinstance(lng_c, (int, float)):
                    latitude = lat_c
                    longitude = lng_c
                    print(f"    > 信息: Region ID {region_id_str} 从 'center' 对象获取到坐标。")
        
        if not (isinstance(latitude, (int, float)) and isinstance(longitude, (int, float))):
            print(f"    > 警告: Region ID {region_id_str} 最终未能在详情API响应中找到有效的坐标。Lat: {latitude}, Lng: {longitude}. DataNode (部分): {str(data_node)[:300]}")
            return None, None, summary_from_detail 

        return latitude, longitude, summary_from_detail

    except requests.exceptions.SSLError as e:
        print(f"    > 错误 (SSL): 获取 Region ID {region_id_str} 详情时发生 SSL 错误: {e}")
        if VERIFY_SSL:
             print(f"    > 提示: 如果持续遇到SSL错误，请检查网络/代理设置，或尝试更新 'requests' 和 'certifi' 库 (pip install --upgrade requests certifi)。作为最后手段，可在脚本顶部设置 VERIFY_SSL = False (有安全风险)。")
    except requests.exceptions.HTTPError as e:
        print(f"    > 错误 (HTTP): 获取 Region ID {region_id_str} 详情时发生HTTP错误: {e.response.status_code} {e.response.reason}")
    except requests.exceptions.RequestException as e: 
        print(f"    > 错误 (网络): 获取 Region ID {region_id_str} 详情时发生网络错误: {e}")
    except json.JSONDecodeError:
        print(f"    > 错误 (JSON): Region ID {region_id_str} 详情API响应JSON解析失败。")
    except Exception as e:
        print(f"    > 错误 (未知): 处理 Region ID {region_id_str} 详情时发生未知错误: {e}")
    return None, None, None 


def fetch_and_store_places(page_param_name="pageNo", page_start_index=0, limit_param_name="pageSize", limit=20):
    """
    从CNKGraph获取行政区划数据并存储到数据库.
    """
    current_page = page_start_index
    print(f"正在获取行政区划数据, 初始页: {current_page}, 每页限制: {limit}...")
    
    conn = None # 初始化conn
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        api_url_template = f"{CNKGRAPH_API_BASE}/api/map/region?{page_param_name}={{page}}&{limit_param_name}={{limit}}"
        total_places_processed_successfully = 0

        api_url = api_url_template.format(page=current_page, limit=limit)
        print(f"  请求API: {api_url}")
        response = requests.get(api_url, timeout=15, verify=VERIFY_SSL)
        response.raise_for_status()
        raw_response_data = response.json()
        
        item_list = []
        if isinstance(raw_response_data, list):
            item_list = raw_response_data
        elif isinstance(raw_response_data, dict) and "data" in raw_response_data and isinstance(raw_response_data["data"], list):
            item_list = raw_response_data["data"]
        elif isinstance(raw_response_data, dict) and "items" in raw_response_data and isinstance(raw_response_data["items"], list):
            item_list = raw_response_data["items"]
        else:
            print(f"错误: /api/map/region API (页: {current_page}) 返回数据格式未知或无有效数据。响应类型: {type(raw_response_data)}。响应片段: {str(raw_response_data)[:500]}")
            return 0 

        if not item_list:
            print(f"第 {current_page} 页未返回任何区域数据，可能已到达末尾或API响应格式不符。")
            return 0 

        for item in item_list:
            region_id = item.get("Id", item.get("id")) 
            name = item.get("Name", item.get("name"))

            if not region_id or not name:
                print(f"警告: 发现不完整的区域条目，已跳过: {item}")
                continue

            dynasty = item.get("Dynasty", item.get("dynasty", "地理区划")) 
            summary_from_list = item.get("Description", item.get("description", name))
            
            # 从列表API的item中获取初始坐标
            initial_latitude = item.get("Latitude", item.get("latitude"))
            initial_longitude = item.get("Longitude", item.get("longitude"))

            print(f"处理区域: {name} (ID: {region_id})。列表API提供坐标: ({initial_latitude}, {initial_longitude})")
            
            latitude_from_detail, longitude_from_detail, summary_from_detail = None, None, None
            if region_id: 
                try:
                    latitude_from_detail, longitude_from_detail, summary_from_detail = get_region_details_and_coords(region_id) 
                    time.sleep(0.3) 
                except Exception as detail_err: 
                    print(f"    > 严重错误: 调用 get_region_details_and_coords 时发生意外: {detail_err}")

            final_summary = summary_from_detail if summary_from_detail and summary_from_detail != "子区域列表" else summary_from_list
            final_details = final_summary 

            # 决定最终坐标：优先详情API，然后列表API
            final_latitude = None
            final_longitude = None

            if latitude_from_detail is not None and longitude_from_detail is not None:
                final_latitude = latitude_from_detail
                final_longitude = longitude_from_detail
                print(f"  > 使用详情API坐标: ({final_latitude}, {final_longitude})")
            elif initial_latitude is not None and initial_longitude is not None:
                final_latitude = initial_latitude
                final_longitude = initial_longitude
                print(f"  > 详情API未提供有效坐标，回退到列表API坐标: ({final_latitude}, {final_longitude})")
            else:
                print(f"  > 警告: ID {region_id} ({name}) 在列表API和详情API中均未能获取有效坐标。")

            if final_latitude is not None and final_longitude is not None:
                try:
                    cursor.execute('''
                        INSERT INTO historical_places (k_id, name, dynasty, summary, details, latitude, longitude, raw_cnkg_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(k_id) DO UPDATE SET
                            name=excluded.name,
                            dynasty=excluded.dynasty,
                            summary=excluded.summary,
                            details=excluded.details,
                            latitude=excluded.latitude,
                            longitude=excluded.longitude,
                            raw_cnkg_data=excluded.raw_cnkg_data,
                            last_updated=CURRENT_TIMESTAMP
                    ''', (str(region_id), name, dynasty, final_summary, final_details, final_latitude, final_longitude, json.dumps(item)))
                    conn.commit()
                    total_places_processed_successfully += 1
                    print(f"  > ID {region_id} ({name}) 数据已存储/更新。最终坐标: ({final_latitude}, {final_longitude})")
                except sqlite3.Error as e:
                    print(f"错误: 存储 ID {region_id} 数据到数据库时发生错误: {e}")
            else:
                print(f"  > ID {region_id} ({name}) 未能获取有效坐标，跳过存储。")
        
        print(f"第 {current_page} 页处理完成，成功存储/更新 {total_places_processed_successfully} 条区域数据（总共从API获取 {len(item_list)} 条）。")
        return len(item_list) 

    except requests.exceptions.SSLError as e:
        print(f"错误 (SSL): 从 /api/map/region API (页: {current_page}) 获取数据时发生 SSL 错误: {e}")
        if VERIFY_SSL:
            print(f"提示: 如果持续遇到SSL错误，请检查网络/代理设置，或尝试更新 'requests' 和 'certifi' 库 (pip install --upgrade requests certifi)。作为最后手段，可在脚本顶部设置 VERIFY_SSL = False (有安全风险)。")
    except requests.exceptions.HTTPError as e:
        print(f"错误 (HTTP): 从 /api/map/region API (页: {current_page}) 获取数据时发生HTTP错误: {e.response.status_code} {e.response.reason}")
    except requests.exceptions.RequestException as e:
        print(f"错误 (网络): 从 /api/map/region API (页: {current_page}) 获取数据时发生网络错误: {e}")
    except json.JSONDecodeError:
        print(f"错误 (JSON): /api/map/region API (页: {current_page}) 响应JSON解析失败。")
    except Exception as e:
        print(f"错误 (未知): 处理 /api/map/region API (页: {current_page}) 数据时发生未知错误: {e}")
    
    return 0 
    


if __name__ == "__main__":
    init_db()
    items_fetched = fetch_and_store_places(page_param_name="pageNo", page_start_index=0, limit_param_name="pageSize", limit=20)
    print(f"\n数据获取任务完成。从API获取了 {items_fetched} 个原始条目进行处理。")

