import { NextIntlClientProvider } from "next-intl";
import LocalizedLoginPage from "../[locale]/login/page";
import messages from "../../messages/ko.json";

export default function LoginPage() {
  return (
    <NextIntlClientProvider locale="ko" messages={messages}>
      <LocalizedLoginPage />
    </NextIntlClientProvider>
  );
}
