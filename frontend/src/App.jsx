import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth.jsx";
import { MusicProvider } from "./components/Music.jsx";
import Shell, { PROFILE_NAV, SubNav, WORK_NAV } from "./components/Shell.jsx";
import BreakRoom from "./pages/BreakRoom.jsx";
import Calendar from "./pages/Calendar.jsx";
import Community from "./pages/Community.jsx";
import Costing from "./pages/Costing.jsx";
import ShareRouter from "./pages/ShareRouter.jsx";
import Marketplace from "./pages/Marketplace.jsx";
import Mentoring from "./pages/Mentoring.jsx";
import { Conversation, MessageList } from "./pages/Messages.jsx";
import PostDetail from "./pages/PostDetail.jsx";
import SupplierDetail from "./pages/SupplierDetail.jsx";
import Supplies from "./pages/Supplies.jsx";
import Handoffs from "./pages/Handoffs.jsx";
import Home from "./pages/Home.jsx";
import Inbox from "./pages/Inbox.jsx";
import Jobs from "./pages/Jobs.jsx";
import Login from "./pages/Login.jsx";
import Payments from "./pages/Payments.jsx";
import Photos from "./pages/Photos.jsx";
import Plan from "./pages/Plan.jsx";
import Helper from "./pages/Helper.jsx";
import Parts from "./pages/Parts.jsx";
import Profile from "./pages/Profile.jsx";
import Quotes from "./pages/Quotes.jsx";
import Rates from "./pages/Rates.jsx";
import Referrals from "./pages/Referrals.jsx";
import Reviews from "./pages/Reviews.jsx";
import Settings from "./pages/Settings.jsx";
import Signup from "./pages/Signup.jsx";
import Team from "./pages/Team.jsx";
import Time from "./pages/Time.jsx";

function RequireSignIn({ children }) {
  const { user } = useAuth();
  const location = useLocation();
  if (user === undefined) return <p className="loading">Loading…</p>;
  if (user === null) return <Navigate to="/login" replace state={{ next: location.pathname }} />;
  return <Shell>{children}</Shell>;
}

// Sign-in screens. Once signed in, go to the page the person originally asked for.
function SignedOutOnly({ children }) {
  const { user } = useAuth();
  const location = useLocation();
  if (user) return <Navigate to={location.state?.next || "/"} replace />;
  return children;
}

export default function App() {
  const { user } = useAuth();
  // The music player sits above the routes so it survives moving between pages.
  const routes = (
    <Routes>
      <Route path="/login" element={<SignedOutOnly><Login /></SignedOutOnly>} />
      <Route path="/signup" element={<SignedOutOnly><Signup /></SignedOutOnly>} />
      <Route path="/" element={<RequireSignIn><Home /></RequireSignIn>} />
      <Route path="/community" element={<RequireSignIn><Community /></RequireSignIn>} />
      <Route path="/posts/:id" element={<RequireSignIn><PostDetail /></RequireSignIn>} />
      <Route path="/share" element={<RequireSignIn><ShareRouter /></RequireSignIn>} />
      <Route path="/share/:kind/:id?" element={<RequireSignIn><ShareRouter /></RequireSignIn>} />
      <Route path="/mentoring" element={<RequireSignIn><Mentoring /></RequireSignIn>} />
      <Route path="/messages" element={<RequireSignIn><MessageList /></RequireSignIn>} />
      <Route path="/messages/:id" element={<RequireSignIn><Conversation /></RequireSignIn>} />
      <Route path="/supplies" element={<RequireSignIn><Supplies /></RequireSignIn>} />
      <Route path="/supplies/parts" element={<RequireSignIn><Parts /></RequireSignIn>} />
      <Route path="/helper" element={<RequireSignIn><Helper /></RequireSignIn>} />
      <Route path="/supplies/:id" element={<RequireSignIn><SupplierDetail /></RequireSignIn>} />
      <Route path="/inbox" element={<RequireSignIn><SubNav items={WORK_NAV} /><Inbox /></RequireSignIn>} />
      <Route path="/jobs" element={<RequireSignIn><SubNav items={WORK_NAV} /><Jobs /></RequireSignIn>} />
      <Route path="/marketplace" element={<RequireSignIn><SubNav items={WORK_NAV} /><Marketplace /></RequireSignIn>} />
      <Route path="/jobs/:id/costing" element={<RequireSignIn><Costing /></RequireSignIn>} />
      <Route path="/calendar" element={<RequireSignIn><SubNav items={WORK_NAV} /><Calendar /></RequireSignIn>} />
      <Route path="/time" element={<RequireSignIn><SubNav items={WORK_NAV} /><Time /></RequireSignIn>} />
      <Route path="/quotes" element={<RequireSignIn><SubNav items={WORK_NAV} /><Quotes /></RequireSignIn>} />
      <Route path="/handoffs" element={<RequireSignIn><SubNav items={WORK_NAV} /><Handoffs /></RequireSignIn>} />
      <Route path="/payments" element={<RequireSignIn><SubNav items={WORK_NAV} /><Payments /></RequireSignIn>} />
      <Route path="/rates" element={<RequireSignIn><SubNav items={WORK_NAV} /><Rates /></RequireSignIn>} />
      <Route path="/profile" element={<RequireSignIn><SubNav items={PROFILE_NAV} /><Profile /></RequireSignIn>} />
      <Route path="/photos" element={<RequireSignIn><SubNav items={PROFILE_NAV} /><Photos /></RequireSignIn>} />
      <Route path="/team" element={<RequireSignIn><SubNav items={PROFILE_NAV} /><Team /></RequireSignIn>} />
      <Route path="/plan" element={<RequireSignIn><Plan /></RequireSignIn>} />
      <Route path="/referrals" element={<RequireSignIn><SubNav items={PROFILE_NAV} /><Referrals /></RequireSignIn>} />
      <Route path="/reviews" element={<RequireSignIn><SubNav items={PROFILE_NAV} /><Reviews /></RequireSignIn>} />
      <Route path="/settings" element={<RequireSignIn><Settings /></RequireSignIn>} />
      <Route path="/break-room" element={<RequireSignIn><BreakRoom /></RequireSignIn>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
  return user ? <MusicProvider>{routes}</MusicProvider> : routes;
}
