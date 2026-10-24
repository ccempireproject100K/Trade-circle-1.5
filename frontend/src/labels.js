// Display names for values the API sends as codes.
export const CATEGORY_NAMES = {
  lumber_building_materials: "Lumber & building materials",
  electrical: "Electrical",
  plumbing: "Plumbing",
  hvac: "HVAC",
  roofing: "Roofing",
  siding_exteriors: "Siding & exteriors",
  paint_coatings: "Paint & coatings",
  flooring: "Flooring",
  tools_equipment: "Tools & equipment",
  fasteners_hardware: "Fasteners & hardware",
  concrete_masonry: "Concrete & masonry",
  landscape_irrigation: "Landscape & irrigation",
  safety_ppe: "Safety & PPE",
  other: "Other",
};

export const KIND_NAMES = {
  supply_question: "Question",
  supplier_review: "Member experience",
  supplier_suggestion: "Supplier suggestion",
  project: "Project",
  lesson: "Lesson from the job",
  equipment: "Equipment experience",
  equipment_question: "Equipment question",
  meetup: "Meetup",
  opening: "Hiring",
  spot: "Member recommendation",
  starting_out: "Starting Out",
};

export const EMPLOYMENT_TYPES = { full_time: "Full time", part_time: "Part time", seasonal: "Seasonal", apprenticeship: "Apprenticeship", temporary: "Temporary" };

export const REPORT_REASONS = {
  spam: "Spam or advertising",
  harassment: "Harassment",
  threat: "Threat",
  fabricated: "Looks made up",
  private_info: "Shares private information",
  other: "Something else",
};

export const EXPERIENCE_NAMES = { positive: "Good experience", mixed: "Mixed experience", negative: "Bad experience" };

// The member's search area is remembered on this device only.
export const savedArea = {
  get() {
    try {
      return JSON.parse(localStorage.getItem("tc-area")) || { near: "", radius: 25 };
    } catch {
      return { near: "", radius: 25 };
    }
  },
  set(area) {
    try {
      localStorage.setItem("tc-area", JSON.stringify(area));
    } catch {
      /* private browsing: just don't remember */
    }
  },
};
