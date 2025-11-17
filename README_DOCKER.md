# 솔루미랩 경리나라 전표 생성 - Docker 배포 가이드

Docker를 사용하여 어디서나 쉽게 배포하고 실행할 수 있습니다.

## 📋 목차

1. [Docker란?](#docker란)
2. [로컬 실행](#로컬-실행)
3. [NAS 배포](#nas-배포)
4. [클라우드 배포](#클라우드-배포)
5. [문제 해결](#문제-해결)

---

## 🐳 Docker란?

**간단한 설명:**
- 프로그램을 "상자(컨테이너)"에 담아서 어디서나 똑같이 실행
- Python 설치, 패키지 설치 등 환경 설정 불필요
- 한 번 만들면 어디서나 실행 가능

**비유:**
```
일반 실행 = 재료 사서 직접 요리
Docker    = 완성된 도시락 데우기
```

---

## 💻 로컬 실행 (개발자/테스트용)

### 사전 준비

1. **Docker 설치**
   - Mac: [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop)
   - Windows: [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop)
   - 설치 후 Docker Desktop 실행 확인

2. **파일 준비**
   ```bash
   cd sollume-finance
   ls  # 다음 파일들이 있는지 확인:
       # - Dockerfile
       # - docker-compose.yml
       # - app.py
       # - Src/거래처마스터.xlsx
   ```

### 실행 방법

#### 방법 1: 스크립트 사용 (추천)

```bash
# 1. 빌드
./docker-build.sh

# 2. 실행
./docker-run.sh

# 3. 브라우저에서 접속
# http://localhost:8501

# 4. 종료
./docker-stop.sh
```

#### 방법 2: Docker Compose 직접 사용

```bash
# 빌드 및 실행 (한 번에)
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 종료
docker-compose down
```

#### 방법 3: Docker 명령어 직접 사용

```bash
# 이미지 빌드
docker build -t sollume-finance .

# 컨테이너 실행
docker run -d \
  -p 8501:8501 \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/processed:/app/processed \
  -v $(pwd)/Src/거래처마스터.xlsx:/app/Src/거래처마스터.xlsx \
  --name sollume-app \
  sollume-finance

# 로그 확인
docker logs -f sollume-app

# 종료
docker stop sollume-app
docker rm sollume-app
```

### 유용한 명령어

```bash
# 컨테이너 상태 확인
docker-compose ps

# 로그 실시간 보기
docker-compose logs -f

# 컨테이너 재시작
docker-compose restart

# 컨테이너 안으로 들어가기
docker-compose exec sollume-app /bin/bash

# 이미지 삭제 (재빌드 전)
docker-compose down --rmi all
```

---

## 🏠 NAS 배포 (Synology)

### 사전 준비

1. **NAS 설정**
   - Docker 패키지 설치 (패키지 센터)
   - SSH 활성화 (제어판 → 터미널 및 SNMP)
   - 외부 접속 설정 (DDNS, 포트 포워딩)

2. **SSH 접속 확인**
   ```bash
   ssh admin@your-nas-ip
   # 비밀번호 입력 후 접속되는지 확인
   ```

### 자동 배포

```bash
./deploy-nas.sh

# 안내에 따라 입력:
# - NAS IP 주소
# - 사용자명 (기본: admin)
```

스크립트가 자동으로:
1. NAS에 디렉토리 생성
2. 파일 전송
3. Docker 이미지 빌드
4. 컨테이너 실행

### 수동 배포

```bash
# 1. NAS에 디렉토리 생성
ssh admin@nas-ip "mkdir -p /volume1/docker/sollume-finance"

# 2. 파일 전송
scp -r . admin@nas-ip:/volume1/docker/sollume-finance/

# 3. NAS에 접속
ssh admin@nas-ip

# 4. 디렉토리 이동
cd /volume1/docker/sollume-finance

# 5. 실행
sudo docker-compose up -d

# 6. 상태 확인
sudo docker-compose ps
sudo docker-compose logs
```

### NAS 접속 주소

**내부 네트워크:**
```
http://nas-ip:8501
```

**외부 접속 (DDNS 설정 후):**
```
http://your-name.synology.me:8501
```

**HTTPS 설정 (리버스 프록시):**
```
https://your-name.synology.me
```

### NAS 리버스 프록시 설정

1. **DSM 접속** → 제어판 → 응용 프로그램 → 리버스 프록시

2. **새 규칙 생성:**
   ```
   설명: Sollume Finance

   소스:
   - 프로토콜: HTTPS
   - 호스트 이름: your-name.synology.me
   - 포트: 443

   대상:
   - 프로토콜: HTTP
   - 호스트 이름: localhost
   - 포트: 8501
   ```

3. **총무 접속:**
   ```
   https://your-name.synology.me
   ```

---

## ☁️ 클라우드 배포

### AWS Lightsail 예시

```bash
# 1. Lightsail 인스턴스 생성 (Ubuntu)

# 2. 인스턴스 접속
ssh ubuntu@instance-ip

# 3. Docker 설치
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 4. Docker Compose 설치
sudo apt-get update
sudo apt-get install docker-compose-plugin

# 5. 프로젝트 파일 전송
scp -r . ubuntu@instance-ip:~/sollume-finance/

# 6. 실행
cd sollume-finance
sudo docker-compose up -d

# 7. 방화벽 설정 (Lightsail 콘솔에서)
# TCP 8501 포트 열기

# 8. 접속
http://instance-ip:8501
```

### 도메인 연결

```bash
# 1. 도메인 구매 및 A 레코드 설정
# sollume.yourdomain.com → instance-ip

# 2. Nginx + Let's Encrypt (HTTPS)
sudo apt-get install nginx certbot python3-certbot-nginx

# 3. Nginx 설정
sudo nano /etc/nginx/sites-available/sollume

# 4. 설정 내용:
server {
    server_name sollume.yourdomain.com;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}

# 5. SSL 인증서
sudo certbot --nginx -d sollume.yourdomain.com

# 6. 접속
https://sollume.yourdomain.com
```

---

## 🔧 문제 해결

### 문제 1: 컨테이너가 시작되지 않음

```bash
# 로그 확인
docker-compose logs

# 흔한 원인:
# - 포트 8501이 이미 사용 중
# - 거래처마스터.xlsx 파일 없음
# - 권한 문제
```

**해결:**
```bash
# 포트 사용 확인
lsof -i :8501  # Mac/Linux
netstat -ano | findstr :8501  # Windows

# 다른 포트 사용 (docker-compose.yml 수정)
ports:
  - "8502:8501"  # 8502로 접속
```

### 문제 2: 파일 업로드 실패

```bash
# 볼륨 권한 확인
ls -la logs/ processed/ uploads/

# 권한 부여
chmod 777 logs processed uploads
```

### 문제 3: 거래처마스터.xlsx 찾을 수 없음

```bash
# 파일 존재 확인
ls -la Src/거래처마스터.xlsx

# 볼륨 마운트 확인
docker-compose exec sollume-app ls -la /app/Src/
```

### 문제 4: 컨테이너는 실행되는데 접속 안 됨

```bash
# 컨테이너 내부에서 확인
docker-compose exec sollume-app curl http://localhost:8501/_stcore/health

# 방화벽 확인
# Mac: 시스템 환경설정 → 보안 및 개인정보보호 → 방화벽
# Windows: Windows Defender 방화벽
```

### 문제 5: NAS 배포 시 SSH 연결 실패

```bash
# SSH 설정 확인
ssh admin@nas-ip

# 안되면:
# 1. NAS DSM → 제어판 → 터미널 및 SNMP → SSH 활성화
# 2. 방화벽에서 22번 포트 허용
# 3. admin 대신 다른 계정 사용해보기
```

---

## 📊 데이터 관리

### 백업

```bash
# 데이터 폴더 백업
tar -czf backup-$(date +%Y%m%d).tar.gz logs/ processed/ Src/거래처마스터.xlsx

# NAS로 전송
scp backup-*.tar.gz admin@nas-ip:/volume1/backup/
```

### 복원

```bash
# 백업 파일 압축 해제
tar -xzf backup-20241115.tar.gz
```

### 로그 정리

```bash
# 오래된 로그 삭제
find logs/ -name "*.log" -mtime +30 -delete

# 또는 로그 로테이션 설정 (docker-compose.yml)
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

---

## 🔄 업데이트

### 코드 업데이트

```bash
# 1. 새 코드 받기 (git 사용 시)
git pull

# 2. 재빌드 및 재실행
docker-compose up -d --build

# 또는
./docker-build.sh
./docker-run.sh
```

### 마스터 파일 업데이트

```bash
# NAS의 경우
scp Src/거래처마스터.xlsx admin@nas-ip:/volume1/docker/sollume-finance/Src/

# 재시작 불필요 (볼륨 마운트로 즉시 반영)
```

---

## 📞 원격 지원

### 로그 수집

```bash
# 전체 로그 다운로드
docker-compose logs > debug.log

# 또는 웹 UI에서 다운로드
# 처리 이력 페이지 → 로그 다운로드 버튼
```

### 개발자 접속

```bash
# NAS에 SSH 접속
ssh admin@nas-ip

# 컨테이너 로그 확인
cd /volume1/docker/sollume-finance
sudo docker-compose logs -f

# 컨테이너 안으로 들어가기
sudo docker-compose exec sollume-app /bin/bash

# 파일 확인
ls -la /app/Src/
cat /app/logs/app.log
```

---

## 🎯 권장 배포 방식

| 상황 | 권장 방법 | 이유 |
|------|----------|------|
| **개발/테스트** | 로컬 Docker | 빠른 테스트, 쉬운 수정 |
| **총무 PC 1대** | NAS Docker | 중앙 관리, 데이터 안전 |
| **여러 PC 접속** | NAS Docker + DDNS | 어디서나 접속 |
| **외부 접속 많음** | 클라우드 | 안정적, 빠른 속도 |

---

## ✨ 장점 요약

- ✅ 환경 설정 불필요 (Python, 패키지 자동 설치)
- ✅ 어디서나 동일하게 실행
- ✅ 업데이트 쉬움 (이미지만 교체)
- ✅ 롤백 가능 (문제 시 이전 버전으로)
- ✅ 격리된 환경 (다른 프로그램 영향 없음)
- ✅ 자동 재시작 (서버 재부팅 시)

---

**즐거운 배포 되세요! 🚀**
