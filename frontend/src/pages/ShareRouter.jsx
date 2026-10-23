import { useParams } from "react-router-dom";
import GuidedPost, { FLOWS, ShareChooser } from "./Share.jsx";
import { ShareEquipment, ShareMeetup, ShareOpening, ShareSpot } from "./ShareForms.jsx";

// /share picks what to share; each kind has its own screen.
export default function ShareRouter() {
  const { kind } = useParams();
  if (FLOWS[kind]) return <GuidedPost key={kind} />;
  if (kind === "equipment") return <ShareEquipment />;
  if (kind === "meetup") return <ShareMeetup />;
  if (kind === "opening") return <ShareOpening />;
  if (kind === "spot") return <ShareSpot />;
  return <ShareChooser />;
}
