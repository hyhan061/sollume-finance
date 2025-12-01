# Oracle Cloud 배포 가이드

## 📋 목차

1. [사전 준비](#사전-준비)
2. [로컬에서 Docker Hub에 푸시](#로컬에서-docker-hub에-푸시)
3. [Oracle Cloud 서버 설정](#oracle-cloud-서버-설정)
4. [애플리케이션 배포](#애플리케이션-배포)
5. [업데이트 방법](#업데이트-방법)
6. [문제 해결](#문제-해결)

---

## 🚀 사전 준비

### Oracle Cloud 인스턴스 정보

- **OS**: Ubuntu 24.04 LTS
- **아키텍처**: ARM64 (Ampere A1)
- **스펙**: VM.Standard.A1.Flex
  - CPU: 4 core OCPU
  - 메모리: 24 GB
  - 네트워크: 4 Gbps

### 필요한 것들

1. **Docker Hub 계정**: hoyeonhan/sollume-lab
2. **Oracle Cloud 인스턴스**: 생성 및 SSH 접속 가능
3. **거래처마스터 파일**: `Src/거래처마스터.xlsx`
4. **로컬 환경**: Docker 및 Docker Buildx 설치

---

## 1️⃣ 로컬에서 Docker Hub에 푸시

### Step 1: Docker Hub 로그인

```bash
docker login
# Username: hoyeonhan
# Password: [your-password]
```

### Step 2: 이미지 빌드 및 푸시

```bash
# 자동 스크립트 실행 (권장)
./docker-push.sh
```

**스크립트가 하는 일**:
- 멀티 플랫폼 빌더 생성 (AMD64 + ARM64)
- Git 태그로부터 버전 자동 감지
- 3개 태그 생성:
  - `hoyeonhan/sollume-lab:latest`
  - `hoyeonhan/sollume-lab:v2.0.0` (버전)
  - `hoyeonhan/sollume-lab:b201329` (커밋 해시)
- Docker Hub에 푸시

### Step 3: 푸시 확인

```bash
# 브라우저에서 확인
open https://hub.docker.com/r/hoyeonhan/sollume-lab

# 또는 CLI로 확인
docker pull hoyeonhan/sollume-lab:latest
```

**예상 소요 시간**: 5-10분 (네트워크 속도에 따라)

---

## 2️⃣ Oracle Cloud 서버 설정

### Step 1: 인스턴스 네트워크 설정

Oracle Cloud 콘솔에서:

1. **Compute** → **Instances** → 인스턴스 선택
2. **Virtual Cloud Network** → **Public Subnet** 선택
3. **Security Lists** → **Default Security List** 선택
4. **Ingress Rules** 추가:

   | 소스 CIDR | IP 프로토콜 | 소스 포트 범위 | 대상 포트 범위 | 설명 |
   |-----------|-------------|----------------|----------------|------|
   | 0.0.0.0/0 | TCP | All | 8501 | Streamlit |
   | 0.0.0.0/0 | TCP | All | 80 | HTTP (선택) |
   | 0.0.0.0/0 | TCP | All | 443 | HTTPS (선택) |

### Step 2: SSH 접속

```bash
# SSH 키로 접속
ssh -i ~/.ssh/oracle-cloud-key.pem ubuntu@<PUBLIC_IP>

# 또는 비밀번호 접속 (설정한 경우)
ssh ubuntu@<PUBLIC_IP>
```

### Step 3: 서버 초기 설정

**방법 1: 자동 스크립트** (권장)

```bash
# 로컬에서 스크립트 전송
scp oracle-setup.sh ubuntu@<PUBLIC_IP>:~

# 서버에서 실행
ssh ubuntu@<PUBLIC_IP>
chmod +x oracle-setup.sh
./oracle-setup.sh

# 재로그인 (docker 그룹 적용)
exit
ssh ubuntu@<PUBLIC_IP>
```

**방법 2: 수동 설정**

```bash
# 시스템 업데이트
sudo apt-get update && sudo apt-get upgrade -y

# Docker 설치
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Docker Compose 설치
sudo apt-get install -y docker-compose-plugin

# 필수 유틸리티
sudo apt-get install -y curl wget git vim htop ufw

# 방화벽 설정
sudo ufw --force enable
sudo ufw allow 22/tcp
sudo ufw allow 8501/tcp

# 재로그인
exit && ssh ubuntu@<PUBLIC_IP>
```

**설치 확인**:

```bash
# Docker 버전 확인
docker --version
docker compose version

# Docker 그룹 확인 (sudo 없이 실행되어야 함)
docker ps

# 시스템 정보
uname -a
free -h
df -h
```

---

## 3️⃣ 애플리케이션 배포

### Step 1: 작업 디렉토리 준비

```bash
# 서버에 접속
ssh ubuntu@<PUBLIC_IP>

# 디렉토리 생성
mkdir -p ~/sollume-finance
cd ~/sollume-finance
```

### Step 2: 거래처마스터 파일 복사

```bash
# 로컬에서 서버로 파일 전송
scp Src/거래처마스터.xlsx ubuntu@<PUBLIC_IP>:~/sollume-finance/

# 서버에서 확인
ls -la ~/sollume-finance/거래처마스터.xlsx
```

### Step 3: 배포 스크립트 실행

**방법 1: 자동 배포** (권장)

```bash
# 로컬에서 스크립트 전송
scp docker-compose.cloud.yml ubuntu@<PUBLIC_IP>:~/sollume-finance/
scp deploy-oracle.sh ubuntu@<PUBLIC_IP>:~/sollume-finance/

# 서버에서 실행
ssh ubuntu@<PUBLIC_IP>
cd ~/sollume-finance
chmod +x deploy-oracle.sh
./deploy-oracle.sh
```

**방법 2: 수동 배포**

```bash
# 서버에 접속
ssh ubuntu@<PUBLIC_IP>
cd ~/sollume-finance

# Docker Compose 파일 생성 (위 내용 복사)
vim docker-compose.cloud.yml

# 이미지 다운로드
docker pull hoyeonhan/sollume-lab:latest

# 컨테이너 시작
docker compose -f docker-compose.cloud.yml up -d

# 상태 확인
docker compose -f docker-compose.cloud.yml ps
docker compose -f docker-compose.cloud.yml logs -f
```

### Step 4: 배포 확인

```bash
# 컨테이너 상태
docker ps

# 로그 확인
docker logs sollume-finance-app

# 헬스체크
curl http://localhost:8501/_stcore/health
```

**브라우저에서 접속**:
```
http://<PUBLIC_IP>:8501
```

---

## 4️⃣ 업데이트 방법

### 새 버전 배포

```bash
# 1. 로컬에서 새 이미지 푸시
./docker-push.sh

# 2. 서버에서 업데이트
ssh ubuntu@<PUBLIC_IP>
cd ~/sollume-finance

# 최신 이미지 다운로드
docker compose -f docker-compose.cloud.yml pull

# 컨테이너 재시작 (무중단)
docker compose -f docker-compose.cloud.yml up -d

# 확인
docker compose -f docker-compose.cloud.yml ps
```

### 롤백 방법

```bash
# 특정 버전으로 롤백
docker compose -f docker-compose.cloud.yml down

# docker-compose.cloud.yml 수정
vim docker-compose.cloud.yml
# image: hoyeonhan/sollume-lab:v1.0.0  # 이전 버전

docker compose -f docker-compose.cloud.yml up -d
```

---

## 5️⃣ 유용한 명령어

### 컨테이너 관리

```bash
# 로그 실시간 보기
docker compose -f docker-compose.cloud.yml logs -f

# 컨테이너 재시작
docker compose -f docker-compose.cloud.yml restart

# 컨테이너 중지
docker compose -f docker-compose.cloud.yml down

# 컨테이너 상태 확인
docker compose -f docker-compose.cloud.yml ps

# 컨테이너 내부 접속
docker exec -it sollume-finance-app /bin/bash
```

### 데이터 관리

```bash
# 로그 파일 확인
ls -lh ~/sollume-finance/logs/

# 처리 결과 확인
ls -lh ~/sollume-finance/processed/

# 디스크 사용량 확인
du -sh ~/sollume-finance/*
df -h
```

### 시스템 모니터링

```bash
# 리소스 사용량
docker stats sollume-finance-app

# 시스템 리소스
htop

# 네트워크 확인
netstat -tuln | grep 8501

# 디스크 공간
df -h
```

---

## 6️⃣ 문제 해결

### 문제 1: 컨테이너가 시작되지 않음

**증상**:
```bash
docker ps
# sollume-finance-app이 없음
```

**해결**:
```bash
# 로그 확인
docker compose -f docker-compose.cloud.yml logs

# 흔한 원인:
# 1. 거래처마스터.xlsx 파일 없음
ls -la ~/sollume-finance/거래처마스터.xlsx

# 2. 포트 충돌
sudo lsof -i :8501

# 3. 메모리 부족
free -h
```

### 문제 2: 브라우저 접속 안 됨

**증상**: `http://<PUBLIC_IP>:8501`이 열리지 않음

**해결**:

1. **컨테이너 확인**:
```bash
docker ps | grep sollume
curl http://localhost:8501/_stcore/health
```

2. **방화벽 확인**:
```bash
# Ubuntu 방화벽
sudo ufw status
sudo ufw allow 8501/tcp

# Oracle Cloud 콘솔
# Security Lists → Ingress Rules → TCP 8501 추가
```

3. **네트워크 확인**:
```bash
netstat -tuln | grep 8501
```

### 문제 3: 이미지 다운로드 실패

**증상**: `docker pull` 실패

**해결**:
```bash
# Docker Hub 로그인 확인
docker login

# 이미지 존재 확인
docker search hoyeonhan/sollume-lab

# 네트워크 확인
ping hub.docker.com
```

### 문제 4: 거래처마스터 파일 오류

**증상**: 앱에서 "거래처마스터 파일을 찾을 수 없습니다" 오류

**해결**:
```bash
# 서버에 파일 존재 확인
ls -la ~/sollume-finance/거래처마스터.xlsx

# 컨테이너 내부 확인
docker exec sollume-finance-app ls -la /app/Src/거래처마스터.xlsx

# 파일 복사
scp Src/거래처마스터.xlsx ubuntu@<PUBLIC_IP>:~/sollume-finance/

# 컨테이너 재시작
docker compose -f docker-compose.cloud.yml restart
```

### 문제 5: 메모리 부족

**증상**: 컨테이너가 자주 재시작됨

**해결**:
```bash
# 메모리 사용량 확인
free -h
docker stats sollume-finance-app

# 스왑 메모리 추가 (oracle-setup.sh에 포함됨)
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# docker-compose.cloud.yml의 리소스 제한 조정
vim docker-compose.cloud.yml
# memory: 10G  # 20G에서 줄임
```

---

## 7️⃣ 보안 고려사항

### 1. 환경변수 관리

중요 정보는 `.env` 파일로 관리:

```bash
# .env 파일 생성
cat > ~/sollume-finance/.env <<EOF
TZ=Asia/Seoul
STREAMLIT_SERVER_HEADLESS=true
# 추가 환경변수
EOF

# docker-compose.cloud.yml 수정
# env_file:
#   - .env
```

### 2. HTTPS 설정 (선택사항)

Let's Encrypt + Nginx:

```bash
# Nginx 설치
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Let's Encrypt 인증서 발급
sudo certbot --nginx -d your-domain.com

# Nginx 설정 (리버스 프록시)
sudo vim /etc/nginx/sites-available/sollume

# 설정 내용:
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}

# Nginx 재시작
sudo ln -s /etc/nginx/sites-available/sollume /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 3. 방화벽 최소화

```bash
# SSH만 허용하고 8501은 내부에서만
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 8501/tcp  # Nginx 사용 시

# Nginx가 localhost:8501로 접근
```

---

## 8️⃣ 백업 및 복원

### 데이터 백업

```bash
# 서버에서 백업 생성
cd ~/sollume-finance
tar -czf backup-$(date +%Y%m%d).tar.gz \
    logs/ \
    processed/ \
    거래처마스터.xlsx \
    docker-compose.cloud.yml

# 로컬로 다운로드
scp ubuntu@<PUBLIC_IP>:~/sollume-finance/backup-*.tar.gz ./
```

### 자동 백업 설정

```bash
# Cron 작업 추가
crontab -e

# 매일 새벽 2시 백업
0 2 * * * cd ~/sollume-finance && tar -czf backup-$(date +\%Y\%m\%d).tar.gz logs/ processed/ 거래처마스터.xlsx && find ~/sollume-finance/backup-*.tar.gz -mtime +7 -delete
```

---

## 9️⃣ 성능 최적화

### Docker 이미지 최적화

이미 적용됨:
- Python 3.11 slim 베이스 이미지
- 멀티스테이지 빌드 (불필요)
- 불필요한 파일 제외 (.dockerignore)

### 리소스 할당

docker-compose.cloud.yml에서:
```yaml
deploy:
  resources:
    limits:
      cpus: '4'      # 전체 CPU 사용
      memory: 20G    # 24GB 중 20GB
    reservations:
      cpus: '2'      # 최소 2 코어 보장
      memory: 4G     # 최소 4GB 보장
```

---

## 🎉 배포 완료!

성공적으로 배포되었다면:

- ✅ http://<PUBLIC_IP>:8501 접속 가능
- ✅ 파일 업로드 및 전표 생성 동작
- ✅ 로그 파일 생성 확인 (`~/sollume-finance/logs/`)
- ✅ 헬스체크 통과

**문의**: hoyeon.han@picoinnov.com
