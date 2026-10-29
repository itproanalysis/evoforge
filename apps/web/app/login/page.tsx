import { NextIntlClientProvider } from "next-intl";
import LocalizedLoginPage from "../[locale]/login/page";
import messages from "../../messages/en.json";

export default function LoginPage() {
  return (
    <NextIntlClientProvider locale="en" messages={messages}>
      <LocalizedLoginPage />
    </NextIntlClientProvider>
  );
}
