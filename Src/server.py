import os
import pandas as pd
from flask import Flask, request, send_file, render_template_string

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
PROCESSED_FOLDER = "processed"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

def process_excel(file_path, date):
    df = pd.read_excel(file_path, engine="openpyxl")
    df = df.dropna()  # 예제: NaN 값 제거
    df["Processed Date"] = date  # 선택한 날짜 추가
    return df

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Excel 파일 업로드 및 처리</title>
</head>
<body>
    <h2>Excel 파일 업로드 및 처리</h2>
    <form action="/" method="post" enctype="multipart/form-data">
        <input type="file" name="file" required>
        <input type="date" name="date" required>
        <input type="submit" value="업로드 및 처리">
    </form>
    {% if download_link %}
        <h3>처리된 파일 다운로드:</h3>
        <a href="{{ download_link }}" download>결과 다운로드</a>
    {% endif %}
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def upload_and_process():
    download_link = None
    if request.method == "POST":
        file = request.files["file"]
        date = request.form["date"]
        if file and file.filename.endswith(".xlsm"):
            filepath = os.path.join(UPLOAD_FOLDER, file.filename)
            file.save(filepath)
            
            # 엑셀 데이터 가공 처리
            df = process_excel(filepath, date)
            
            processed_filename = file.filename.replace(".xlsm", "_processed.xls")
            processed_filepath = os.path.join(PROCESSED_FOLDER, processed_filename)
            df.to_excel(processed_filepath, index=False)
            
            download_link = f"/download/{processed_filename}"
            os.remove(filepath)
    return render_template_string(HTML_TEMPLATE, download_link=download_link)

@app.route("/download/<filename>")
def download_file(filename):
    return send_file(os.path.join(PROCESSED_FOLDER, filename), as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
