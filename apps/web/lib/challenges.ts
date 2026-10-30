export interface Challenge {
  id: string;
  title: { en: string; ko: string };
  rounds: { en: string[]; ko: string[] };
}

// Fun multi-round builds. Every mission asks for something visible in the page render(state) returns, so the
// judge's hidden tests can check it (browser-only behaviour such as storage or button clicks cannot be scored).
export const CHALLENGES: Challenge[] = [
  {
    id: "bakery",
    title: { en: "Bakery site", ko: "빵집 홈페이지" },
    rounds: {
      en: [
        "A landing page for a bakery called Sunrise Bakery with a heading and a list of three breads.",
        "Add a price in dollars next to each bread, like $3.50.",
        "Mark one bread as Today's special with a highlighted label.",
        "Add a footer with the opening hours Mon-Sat 7:00-18:00 and a phone number.",
      ],
      ko: [
        "Sunrise Bakery라는 빵집의 제목과 빵 3개 목록이 있는 첫 페이지를 만드세요.",
        "각 빵 옆에 $3.50처럼 달러 가격을 표시하세요.",
        "빵 하나에 '오늘의 추천' 강조 표시를 붙이세요.",
        "영업시간 Mon-Sat 7:00-18:00과 전화번호가 있는 하단 영역을 추가하세요.",
      ],
    },
  },
  {
    id: "tip-calculator",
    title: { en: "Tip calculator", ko: "팁 계산기" },
    rounds: {
      en: [
        "A tip calculator: given a bill amount and a tip percent, show the tip and the total with two decimals.",
        "Add splitting the total between a number of people and show the amount per person.",
        "Add a round-up option that rounds the amount per person up to the next whole dollar.",
      ],
      ko: [
        "팁 계산기: 금액과 팁 비율이 주어지면 팁과 합계를 소수 둘째 자리까지 보여 주세요.",
        "인원수로 합계를 나눠 1인당 금액을 보여 주세요.",
        "1인당 금액을 다음 정수 달러로 올림하는 옵션을 추가하세요.",
      ],
    },
  },
  {
    id: "password-meter",
    title: { en: "Password meter", ko: "비밀번호 강도 측정기" },
    rounds: {
      en: [
        "A password page: given a password, show Weak, Fair or Strong (8+ characters, a digit and a symbol each add a point).",
        "Below the label, list every rule the password does not meet yet.",
        "Show Very strong when the password has 12+ characters and meets every rule.",
      ],
      ko: [
        "비밀번호가 주어지면 Weak, Fair, Strong 중 하나를 보여 주세요 (8자 이상, 숫자, 기호가 각각 1점).",
        "라벨 아래에 아직 충족하지 못한 규칙을 모두 나열하세요.",
        "12자 이상이고 모든 규칙을 충족하면 Very strong을 보여 주세요.",
      ],
    },
  },
  {
    id: "todo-list",
    title: { en: "To-do list", ko: "할 일 목록" },
    rounds: {
      en: [
        "A to-do page that shows the given tasks as a list, each with its title.",
        "Show completed tasks with a done style and show how many tasks remain.",
        "Add a filter (all, active, done) that shows only the matching tasks.",
        "Show the message All done! when every task is completed.",
      ],
      ko: [
        "주어진 할 일들을 제목과 함께 목록으로 보여 주는 페이지를 만드세요.",
        "완료된 일은 완료 스타일로 표시하고 남은 일의 개수를 보여 주세요.",
        "전체, 진행 중, 완료 필터를 추가해 해당하는 일만 보여 주세요.",
        "모든 일이 완료되면 All done! 메시지를 보여 주세요.",
      ],
    },
  },
  {
    id: "unit-converter",
    title: { en: "Unit converter", ko: "단위 변환기" },
    rounds: {
      en: [
        "A length converter: given a value in meters, show it in kilometers and miles with three decimals.",
        "Add weight: given grams, show kilograms and pounds with three decimals.",
        "Add temperature: given Celsius, show Fahrenheit with one decimal.",
      ],
      ko: [
        "길이 변환기: 미터 값이 주어지면 킬로미터와 마일을 소수 셋째 자리까지 보여 주세요.",
        "무게를 추가하세요: 그램이 주어지면 킬로그램과 파운드를 소수 셋째 자리까지 보여 주세요.",
        "온도를 추가하세요: 섭씨가 주어지면 화씨를 소수 첫째 자리까지 보여 주세요.",
      ],
    },
  },
];

export function planFits(remaining: number | null, rounds: number): boolean {
  if (remaining === null || remaining === undefined) return true;
  return rounds <= remaining;
}
