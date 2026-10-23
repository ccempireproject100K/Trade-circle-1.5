import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, label } from "../api.js";
import { PostCard, ReportButton } from "../components/Community.jsx";
import { Notice } from "../components/Form.jsx";
import { CATEGORY_NAMES, savedArea } from "../labels.js";

const unknown = (text) => (!text || text === "unknown" ? <span className="muted">Not confirmed</span> : text);

export default function SupplierDetail() {
  const { id } = useParams();
  const [s, setS] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const near = savedArea.get().near;
    api(`/suppliers/${id}${near ? `?near=${encodeURIComponent(near)}` : ""}`).then(setS).catch((err) => setError(err.message));
  }, [id]);

  if (!s) return error ? <Notice error={error} /> : <p className="loading">Loading…</p>;
  const ships = s.ships_to === "nationwide" ? "Nationwide" : Array.isArray(s.ships_to) ? s.ships_to.join(", ") : "unknown";
  const e = s.experiences;

  return (
    <>
      <p className="small"><Link to="/supplies">← Supplies &amp; Vendors</Link></p>
      <h1>{s.name}</h1>

      <section className="card facts stack">
        <div>
          <h2 style={{ margin: 0 }}>Directory information</h2>
          <p className="small muted" style={{ margin: "2px 0 0" }}>Provided by Trade Circle from public sources. A directory entry, not an endorsement.</p>
        </div>
        <dl>
          {s.website && <><dt>Website</dt><dd><a href={s.website} target="_blank" rel="noreferrer nofollow">{s.website.replace(/^https:\/\//, "")}</a></dd></>}
          <dt>Supplies</dt><dd>{s.offers || s.categories.map((c) => CATEGORY_NAMES[c]).join(", ")}</dd>
          <dt>Trades</dt><dd>{s.trades.length ? s.trades.map(label).join(", ") : unknown()}</dd>
          <dt>Locations</dt>
          <dd>
            {s.locations.length > 0
              ? s.locations.map((l) => <div key={l.label + l.address}>{[l.address, l.label].filter(Boolean).join(", ")}{l.distance_miles != null && ` · ${l.distance_miles} mi`}</div>)
              : s.branch_note || unknown()}
          </dd>
          <dt>Delivery</dt><dd>{unknown(s.delivery)}</dd>
          <dt>Ships to</dt><dd>{unknown(ships)}</dd>
          <dt>Business account</dt><dd>{unknown(s.business_account)}</dd>
          <dt>What Trade Circle checked</dt>
          <dd className="small">{s.verification.map((v) => <div key={v}>{v}</div>)}</dd>
        </dl>
        <p className="small muted" style={{ margin: 0 }}>
          Listed by {s.added_by}. Something wrong? <ReportButton targetType="supplier" targetId={s.id} label="Report this listing" />
        </p>
      </section>

      <section className="stack">
        <div className="row-between">
          <h2 style={{ margin: 0 }}>Member experiences</h2>
          <Link className="btn btn-small" to={`/supplies?recommend=${s.id}`}>Share yours</Link>
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          Opinions of Trade Circle members, not facts checked by Trade Circle.{" "}
          {e.posts > 0 && `${e.positive} good · ${e.mixed} mixed · ${e.negative} bad.`}
        </p>
        {s.member_posts.length === 0 ? (
          <p className="empty">No member posts about this supplier yet.</p>
        ) : (
          <ul className="items">{s.member_posts.map((p) => <PostCard key={p.id} post={p} />)}</ul>
        )}
      </section>

      <p className="small muted" style={{ marginTop: 24 }}>
        Do you represent this business? <a href={`/suppliers/${s.id}/remove`}>Request removal of this listing</a>.
      </p>
    </>
  );
}
