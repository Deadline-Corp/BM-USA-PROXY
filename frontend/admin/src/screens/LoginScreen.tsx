import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useLocation, useNavigate } from "react-router-dom";
import { authApi } from "@/shared/api/endpoints";
import { apiErrorMessage } from "@/shared/api/client";
import { useAuthStore } from "@/shared/auth/authStore";
import { Button } from "@/shared/components/Button";
import { Input } from "@/shared/components/form/Input";
import { isSafeInternalPath } from "@/shared/lib/safePath";
import { strings } from "@/shared/strings";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(1, "Password is required"),
});

type LoginForm = z.infer<typeof loginSchema>;

export function LoginScreen() {
  const navigate = useNavigate();
  const location = useLocation();
  const setSession = useAuthStore((s) => s.setSession);
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema) });

  async function onSubmit(values: LoginForm) {
    setFormError(null);
    try {
      const { access_token, admin } = await authApi.login(values);
      setSession(access_token, admin);
      // `from` comes from the address bar via AuthGate — only follow it if it is a
      // real internal path, never a protocol-relative/backslash-smuggled absolute URL.
      const requested = (location.state as { from?: string } | null)?.from;
      const from = requested && isSafeInternalPath(requested) ? requested : "/";
      navigate(from, { replace: true });
    } catch (err) {
      setFormError(apiErrorMessage(err, strings.auth.genericError));
    }
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center px-4">
      <div className="w-full max-w-[400px]">
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <div className="w-10 h-10 flex-none rounded-xl bg-accent border border-accent-2 grid place-items-center text-white relative overflow-hidden">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" width={24} height={24}>
              <rect x="6" y="2.5" width="12" height="19" rx="2.5" />
              <path d="M9.5 6.5h5" />
              <path d="M11 18.5h2" />
              <path d="M3 11c0-2.5 1.2-4.5 3-6" />
              <path d="M21 11c0-2.5-1.2-4.5-3-6" />
            </svg>
            <span className="absolute bottom-0 right-0 w-3.5 h-3.5 bg-danger rounded-tl-[5px]" />
          </div>
          <div>
            <div className="font-head font-semibold text-[1.1rem] tracking-[-0.01em] text-text">
              {strings.app.name}
            </div>
            <div className="text-[.76rem] text-text-3">{strings.app.tagline}</div>
          </div>
        </div>

        <div className="bg-surface border border-border rounded-lg shadow-lg p-7">
          <h1 className="text-[1.35rem] mb-1">{strings.auth.loginTitle}</h1>
          <p className="text-[.86rem] text-text-2 mb-6">{strings.auth.loginSubtitle}</p>

          <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              label={strings.auth.emailLabel}
              placeholder="operator@bmusaproxy.com"
              error={errors.email?.message}
              {...register("email")}
            />
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              label={strings.auth.passwordLabel}
              placeholder="••••••••"
              error={errors.password?.message}
              {...register("password")}
            />

            {formError && (
              <div className="text-[.82rem] text-danger bg-danger-soft border border-danger-line rounded-lg px-3 py-2.5">
                {formError}
              </div>
            )}

            <Button type="submit" variant="primary" isLoading={isSubmitting} className="mt-1 w-full">
              {isSubmitting ? strings.auth.submitting : strings.auth.submit}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
