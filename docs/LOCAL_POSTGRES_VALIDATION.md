# Windows에서 PostgreSQL 계약 검증

2026-10-27, PostgreSQL 15.19에서 `validate_package.py --pg`를 실제 실행했다.
참조 테스트 **112개**, core/context SQL 검사 **96개**, C1–C9 전체가 통과했다.
검증 후 임시 서버를 중지하고 해당 클러스터 디렉터리를 삭제한 것을 확인했다.

## 실행

EDB의 [공식 PostgreSQL 바이너리 페이지](https://www.enterprisedb.com/download-postgresql-binaries)에서
Windows x86-64 PostgreSQL 15.19 ZIP을 받아 `pgsql/bin`, `pgsql/lib`, `pgsql/share`를
`.local/postgresql-15.19/` 아래에 보존한다. 시스템 설치는 필요하지 않다.

이번에 사용한 [배포 파일](https://get.enterprisedb.com/postgresql/postgresql-15.19-5-windows-x64-binaries.zip)의
로컬 계산 SHA-256은 `49e0690194d9fe2bb4d7d6587fdddaa85a3eaaafe2fd5480e0916fcb25d0143e`다.
바이너리는 Git에서 제외했다. 실행기는 바이너리를 자동 다운로드하지 않는다.

저장소 루트에서 실행한다. Git for Windows의 Bash가 필요하다.

```powershell
python -m pip install -r tools/requirements-validation.txt
python tools/validate_local_pg.py
```

다른 설치 경로를 지정할 수도 있다.

```powershell
python tools/validate_local_pg.py --pg-bin 'C:\path\to\pgsql\bin'
```

API 의존성을 설치한 Python에서 `--kernel-tests`를 추가하면 실제 PostgreSQL 어댑터 수용 테스트도 실행한다.
[어댑터 검증 절차](POSTGRES_KERNEL.md)에 준비와 범위를 기록했다.

## 실행기의 동작

- 저장소의 `.local/pg-tests/` 아래에 고유한 일회용 클러스터를 생성한다.
- 서버는 `127.0.0.1`의 비어 있는 포트에서만 접속을 받는다.
- 전역 PATH·시스템 서비스와 배포용 `DATABASE_URL`은 변경하거나 사용하지 않는다.
- 원본 계약과 SQL 검사 스크립트를 변경하지 않고 패키지 검증기의 `--pg` 경로를 사용한다.
- Windows의 서버 프로세스가 파이프를 상속해 실행기가 멈추지 않도록 시작 로그는 파일로 받는다.
- 성공·실패 후 서버를 중지한다. 중지가 확인된 자체 클러스터만 경로를 검사한 뒤 삭제한다.
  중지 여부가 불명확하면 클러스터를 보존하고 오류를 반환한다.
- 결과는 `.local/validation-postgres.log`에 저장한다. SQL 실패 시 전체 진단 로그도 별도로 남긴다.

이 검증으로 SQL의 예약·원장·RLS·병합 승인 계약을 확인했다.
FastAPI의 메모리 원장을 PostgreSQL에 연결하는 작업, 실제 Runner, 공급사 영수증 대사,
클라우드 배포와 컨테이너 실행 검증은 별도 항목으로 남아 있다.
