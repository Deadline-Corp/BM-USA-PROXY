import { Link } from "react-router-dom";
import { Button } from "@/shared/components/Button";

export function NotFoundScreen() {
  return (
    <div className="min-h-screen bg-bg flex items-center justify-center px-4">
      <div className="text-center">
        <div className="font-mono text-[3rem] font-semibold text-text-3 leading-none">404</div>
        <p className="text-text-2 mt-3 mb-6">This screen doesn't exist.</p>
        <Link to="/">
          <Button variant="primary">Back to dashboard</Button>
        </Link>
      </div>
    </div>
  );
}
