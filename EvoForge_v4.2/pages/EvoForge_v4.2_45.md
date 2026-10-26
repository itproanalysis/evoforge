<!-- PAGE:45/50 -->

# 45. 위협 모델과 공급망 위험

> **목적:** 보호 자산·경계·위협·통제를 하나의 등록부로 관리한다. · **결정:** D-013, D-017, D-019, D-026, D-027, D-042, D-047 · **계약:** —

### 보호 자산
**플랫폼 공급사 키**(가장 중요한 자산: 유출 시 모든 테넌트 비용·데이터 위험), 고객 저장소, GitHub 설치 권한, CI 비밀, Evidence Vault 원문·DEK, 과금 원장·크레딧, 조직·사용자 정보. 신뢰 경계: `Browser↔API`, `Chat/MCP↔Gateway`, `LLM↔Broker`, `Runner↔Git/Network`, `Worker↔DB`, `Tenant A↔Tenant B`, `Research↔Customer`.

### 위협 등록부(OWASP Agentic Top 10 2026 대응 포함)
| 위협 | 통제 |
|---|---|
| ASI01 목표 탈취 / Prompt Injection | 저장소·로그·논문은 비신뢰, untrusted는 L0/L1 금지, 최상위 Objective 변경 권한 분리, 도구 정책 사전 검증. **필터가 아니라 구조로 막는다**: 적응형 공격은 최신 방어의 85% 이상을 통과한다(2601.17548). 계획(무엇을 호출할지)은 신뢰 컨텍스트에서 먼저 확정하고, 비신뢰 데이터는 값으로만 흐르며 제어 흐름을 바꾸지 못한다(CaMeL 계열, 2503.18813). 부작용 도구는 정책 엔진 + 위험 명령 확인을 거친다 |
| ASI02 도구 악용 | typed tool, 정책 엔진 사전 검증, 최소 노출 |
| ASI03 신원·권한 남용 | OIDC, capability lease, 역할≠권한, 재인증 승인 |
| ASI04 공급망 | 공식 SDK·고정 의존성·SBOM·서명 이미지, LiteLLM 2026-10-21 사고 runbook, BSL 코드 유입 차단 |
| ASI05 임의 코드 실행 | microVM, egress deny, 키·메타데이터 차단 |
| ASI06 기억 오염 | provenance·quarantine, `bad_pattern` 자동 승격 금지 |
| ASI07 에이전트 메시지 위조 | 서명·조직 바인딩, 폴더 `auth_binding` |
| ASI08 연쇄 실패 | circuit breaker, backpressure, 공급사 어댑터 차단 스위치 |
| ASI09 인간 신뢰 악용 | 구조화된 영향 미리보기·확인 UI, 위험 명령 확정 |
| ASI10 Rogue Agent | 격리·권한 회수·Lease 폐기 |
| 플랫폼 키 유출 | Broker 단일 복호화 신원, 키 접근 이상 탐지, 즉시 회전, 테넌트별 하위 키(지원 시) |
| 크레딧·Runner 악용 | 선결제, 예약 하드캡, 결제 검증, 채굴·스캔 탐지 |
| 캐시 사이드채널 | 테넌트 namespace 솔트 |
| ref 존재 오라클 | 무작위 grant, 외부/미존재 동일 `not_found` |
| XML entity expansion·selector 경로 탈출 | DOCTYPE/ENTITY 거부, 닫힌 selector 문법 |
| SSRF(A2A/MCP) | DNS 재확인, 사설 IP·리다이렉트 차단 |
| 벤치마크 조작 / 보상 해킹 | hidden suite, 검증기 불변, pristine 재채점, 증거 해시, `GH_INTEGRITY`(오라클 강도·held-out 격차·조회 테이블·변조 탐지), 평가 샌드박스 git 이력 제거 |
| 투기 실행 부작용 | 읽기 전용 5종만 투기, 부작용 접두사 금지 목록, 순서 커밋 + read set 검증 |
| 연구 공급망(M6) | 논문 지시문 무시, 가짜·철회 논문 추적, 의존성 pin·스캔, 격리 Runner, 라이선스 심사 |

### 원칙
효율을 위해 통제를 약화하지 않는다. 최적화 실험에서 보안 우회가 생기면 10X 점수와 무관하게 실격이다. 안전한 기본값: 고객 코드 외부망 차단, 공급사별 데이터 전송 동의, Chat 최소 권한, 자동 배포 꺼짐. Admin 정책 변경은 별도 감사 이벤트.

### 요구사항
| ID | 요구사항 | 수용 기준 |
|---|---|---|
| R45-1 | 매 배포 자동 시험 | 권한 상승 금지, 도구 입력 검증, egress 차단, 검증 결과 변조 방지, 긴급 정지 |
| R45-2 | 외부 점검 | M4 전 외부 침투 시험, OWASP GenAI/Agentic·ASVS 항목 점검 |
| R45-3 | 키 사고 훈련 | 플랫폼 키 유출 가정 훈련(탐지 → 회전 → 영향 테넌트 통지) 분기 1회 |
| R45-4 | 적응형 인젝션 | 공개 적응형 공격 모음(저장소·이슈·도구 결과 경로)을 매 릴리스 실행, 부작용 도구의 비인가 호출 0건 (CR-11) |

---
