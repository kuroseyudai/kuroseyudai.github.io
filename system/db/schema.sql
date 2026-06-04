CREATE TABLE keywords (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  keyword       TEXT NOT NULL,
  language      TEXT NOT NULL,
  search_volume INTEGER,
  cpc           DECIMAL,
  competition   DECIMAL,
  score         DECIMAL,
  genre         TEXT,
  status        TEXT DEFAULT 'pending',
  created_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE articles (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  keyword_id      UUID REFERENCES keywords(id),
  language        TEXT NOT NULL,
  title_a         TEXT,
  title_b         TEXT,
  content         TEXT,
  meta_desc       TEXT,
  affiliate_links JSONB,
  status          TEXT DEFAULT 'draft',
  wp_post_id      INTEGER,
  created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE publications (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  article_id   UUID REFERENCES articles(id),
  platform     TEXT,
  url          TEXT,
  published_at TIMESTAMP,
  status       TEXT
);

CREATE TABLE ab_tests (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  article_id     UUID REFERENCES articles(id),
  title_winner   TEXT,
  pv_a           INTEGER,
  pv_b           INTEGER,
  ctr_a          DECIMAL,
  ctr_b          DECIMAL,
  is_significant BOOLEAN,
  decided_at     TIMESTAMP
);

CREATE TABLE performance (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  article_id    UUID REFERENCES articles(id),
  date          DATE NOT NULL,
  pv            INTEGER,
  revenue_ad    DECIMAL,
  revenue_aff   DECIMAL,
  total_revenue DECIMAL,
  api_cost      DECIMAL,
  roi           DECIMAL,
  UNIQUE(article_id, date)
);
