-- Documentation-only research namespace. Do not apply to the production database.
CREATE SCHEMA IF NOT EXISTS research_edge;

CREATE TABLE research_edge.research_datasets (
  dataset_id text PRIMARY KEY, created_at timestamptz NOT NULL, schema_version text NOT NULL,
  manifest jsonb NOT NULL, checksum text NOT NULL, universe_completeness text NOT NULL
);
CREATE TABLE research_edge.research_experiments (
  experiment_id text PRIMARY KEY, created_at timestamptz NOT NULL, dataset_id text NOT NULL,
  git_sha text NOT NULL, git_dirty boolean NOT NULL, strategy_contract_hash text NOT NULL,
  config_hash text NOT NULL, random_seed bigint NOT NULL, manifest jsonb NOT NULL
);
CREATE TABLE research_edge.research_opportunities (
  opportunity_id text PRIMARY KEY, experiment_id text NOT NULL, decision_time timestamptz NOT NULL,
  symbol text NOT NULL, timeframe text NOT NULL, research_partition text NOT NULL,
  features jsonb NOT NULL, labels jsonb NOT NULL, context jsonb NOT NULL,
  accepted boolean NOT NULL, rejection_code text NOT NULL, rejection_detail jsonb NOT NULL
);
CREATE TABLE research_edge.research_trades (
  trade_id text PRIMARY KEY, opportunity_id text NOT NULL, result jsonb NOT NULL
);
CREATE TABLE research_edge.research_trade_events (
  trade_id text NOT NULL, event_index integer NOT NULL, event_time timestamptz NOT NULL,
  previous_state text NOT NULL, new_state text NOT NULL, price numeric NOT NULL, reason text NOT NULL,
  PRIMARY KEY (trade_id, event_index)
);
CREATE TABLE research_edge.research_metrics (
  experiment_id text NOT NULL, metric_name text NOT NULL, metric_value jsonb NOT NULL,
  PRIMARY KEY (experiment_id, metric_name)
);
CREATE TABLE research_edge.research_artifacts (
  experiment_id text NOT NULL, artifact_name text NOT NULL, sha256 text NOT NULL,
  storage_uri text NOT NULL, PRIMARY KEY (experiment_id, artifact_name)
);
