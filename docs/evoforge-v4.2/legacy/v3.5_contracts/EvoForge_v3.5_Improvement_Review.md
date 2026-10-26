# EvoForge v3.5 — Caveman 참고 기술 적용 결과

## 출처 및 검토
- 사용자 제공 이미지: Caveman의 Prompt Compression, Go Proxy, CCR(SQLite), CLI Agent Harness, 모델별 Prompt Cache, 공유 Memory/Files 설명. 그림의 성능·이용 가능성 주장은 해당 프로젝트의 설계/주장으로 취급하며 독립 확인하지 않음.
- upstream: https://github.com/JuliusBrussee/caveman. Compression Engine/CCR 원문 복구 방식 참고.
- 라이선스: `LICENSING.md`의 3.0.0+ Apache-2.0 확인. 과거 BSL 라이선스 결과는 해당 릴리스에만 적용.
- 공급사: OpenAI/Anthropic/Gemini 캐시 규약, 지원 모델/비용/TTL은 서로 달라 Capabilities Registry로 관리. 모델 간 KV 공유 불가.

## v3.4에서 발견된 부족한 부분
1. `Artifact-first Handoff` 방향은 있었지만 **원문 보존 후 비가역 압축** 계약이 없었음.
2. 요약 중 사라진 버그·Assertion을 **반드시 복원·검증**하는 경로가 불충분했음.
3. Provider Native Cache와 압축의 **상충 비용** 비교가 부족했음.
4. API/MCP/Folder AI의 **원문 복원 능력 검사**가 없었음.
5. Mission Control에서 **컨텍스트 유실·복원 증거·실제 절감액**을 관찰할 수 없었음.
6. 멀티테넌트 SaaS에서 Caveman 로컬 SQLite를 그대로 옮기면 권한·데이터 보존 문제가 발생함.

## 개선 결정
- 핵심 P0: Context Compiler(유형별), Tenant-Scoped Vault, Recovery Tool, Role Packets, Native Cache Planner.
- P1: 파일 AST·HTML·테이블 압축, 평가/관측성 강화, 상용 Caveman 코드 격리 검증.
- 보류: 전모델 KV 교환, 전체 자동압축, 비검증 토큰 절감률·10X 수치 주장.

## 5-Agent 협업과 기대 변화
기존의 대화 복제 방식을 `TaskContract + Verified Facts + ArtifactManifest + Evidence Retriever`로 전환. Builder가 필요한 소스 코드만 보고, Critic은 전체 Diff에 접근. Navigator/Integrator는 유효한 결정·검증증명서로 판단. 이로써 반복 토큰 낭비 감소 가능성이 있지만 성과는 평가 전 미검증.

## 안전·품질 통제
- 원문 저장 실패 시 손실 압축 불허; 원본 반환도 불가하면 BLOCK.
- 평가/보안/정책과 관련된 증거는 원문 접근 필수.
- 복원 Ref/Content Hash 자체는 권한 증명이 아님.
- Prompt Injection, stale context, provider privacy constraints, cache write costs 대응.

## 실측 필요
원본 vs 선택적 vs 복원가능 압축 vs 공급사 캐시 vs 혼합 A/B. 정확성·회귀 차단·검토 실패·원문복원·실제 API 청구액·전체 실행시간·유효 개선 수를 기록. **10X는 제품 목표이며 보장하지 않음**.

## 정합성 테스트 범위
50페이지 번호·스키마 형식·예시 유효성·ZIP 무결성 검증 수행. 실서비스 API, DB 마이그레이션, 공급사 캐시 실측, 보안 침투 시험은 미실시.
