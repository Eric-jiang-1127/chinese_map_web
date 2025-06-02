# backend_api_server.py
from flask import Flask, jsonify, request
from flask_cors import CORS  # 引入CORS扩展，用于处理跨域请求
import sqlite3

app = Flask(__name__)
CORS(
    app
)  # 为所有路由启用CORS，允许来自任何源的请求。在生产环境中应配置更严格的CORS策略。

DB_NAME = "hanmo_yutu.db"


def query_db(query, args=(), one=False):
    """通用数据库查询函数"""
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row  # 使得查询结果可以像字典一样通过列名访问
        cur = conn.cursor()
        cur.execute(query, args)
        rv = cur.fetchall()
        conn.close()
        # 如果one为True，则返回单条记录；否则返回所有记录
        return (rv[0] if rv else None) if one else rv
    except sqlite3.Error as e:
        print(f"数据库查询错误: {e}")
        # 在实际应用中，这里应该记录更详细的错误日志
        return None


@app.route("/api/places", methods=["GET"])
def get_places():
    """获取地点列表的API接口，支持按朝代和关键词筛选"""
    dynasty_filter = request.args.get("dynasty")  # 从查询参数获取朝代筛选条件
    keyword_filter = request.args.get("keyword")  # 从查询参数获取关键词筛选条件

    # 基础SQL查询语句，只选择包含有效经纬度的地点
    query_sql = "SELECT id, k_id, name, dynasty, summary, latitude, longitude FROM historical_places WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    params = []  # 用于存储SQL查询参数的列表

    # 如果提供了朝代筛选条件且不是"all"
    if dynasty_filter and dynasty_filter.lower() != "all":
        query_sql += " AND dynasty = ?"  # 添加朝代筛选到SQL语句
        params.append(dynasty_filter)  # 添加朝代参数

    # 如果提供了关键词筛选条件
    if keyword_filter:
        query_sql += " AND (name LIKE ? OR summary LIKE ?)"  # 添加关键词筛选到SQL语句 (模糊匹配名称或摘要)
        keyword_like = f"%{keyword_filter}%"  # 构建模糊匹配的模式
        params.extend([keyword_like, keyword_like])  # 添加关键词参数

    query_sql += " ORDER BY name LIMIT 100"  # 默认按名称排序，并限制最多返回100条记录以避免过大数据量

    places_rows = query_db(query_sql, params)  # 执行数据库查询

    # 如果数据库查询出错
    if places_rows is None:
        return (
            jsonify({"error": "获取地点数据时发生数据库错误"}),
            500,
        )  # 返回500服务器错误

    # 将数据库查询结果 (Row对象列表) 转换为字典列表
    places_list = [dict(row) for row in places_rows]
    return jsonify(places_list)  # 返回JSON格式的地点列表


@app.route(
    "/api/places/<string:k_id_value>", methods=["GET"]
)  # 改为接收k_id作为路径参数
def get_place_detail_by_k_id(k_id_value):
    """根据CNKGraph的k_id获取单个地点的详细信息"""
    # 注意：这里的 place_id 是 CNKGraph 的 k_id
    place_row = query_db(
        "SELECT * FROM historical_places WHERE k_id = ?", (k_id_value,), one=True
    )

    if place_row is None:
        return (
            jsonify({"error": "未找到指定K_ID的地点"}),
            404,
        )  # 如果未找到，返回404错误

    return jsonify(dict(place_row))  # 返回JSON格式的地点详情


# 之前的 /api/places/<int:place_id> 接口如果不再需要，可以移除或注释掉
# @app.route('/api/places/<int:place_id>', methods=['GET'])
# def get_place_detail(place_id):
#     """根据本地数据库的自增id获取单个地点的详细信息"""
#     place_row = query_db("SELECT * FROM historical_places WHERE id = ?", (place_id,), one=True)
#     if place_row is None:
#         return jsonify({"error": "未找到指定ID的地点"}), 404
#     return jsonify(dict(place_row))

if __name__ == "__main__":
    # 提示用户先运行数据获取脚本
    print("确保已运行 backend_data_ingestion.py 来创建和填充数据库 hanmo_yutu.db")
    print("Flask API 服务器正在启动，端口为 5001...")
    # 运行Flask应用，开启调试模式，监听在5001端口
    # debug=True 只应在开发环境中使用
    app.run(debug=True, port=5001)
