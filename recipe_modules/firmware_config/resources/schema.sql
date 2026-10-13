-- Schema of the firmware build metadata databases (b/571108483).
--
-- Both `build_metadata` and `build_metadata_staging` in the `firmware-metadata`
-- instance of the `firmware-bigquery` project use it. To apply it to a new
-- database or to add the statements of a later change:
--   gcloud spanner databases ddl update <database> \
--     --instance=firmware-metadata --project=firmware-bigquery \
--     --ddl-file=schema.sql
--
-- publish_target_configs.py writes it. One config set holds the resolved Kconfig
-- symbols of a target and is stored once, however many builds produce it.

-- One row per build that published configs. Branch and ManifestCommitId are the
-- branch and the commit of the manifest that the build synced, which pins the
-- revision of every project.
CREATE TABLE Builds (
  BuildId INT64 NOT NULL,
  Builder STRING(256) NOT NULL,
  Bucket STRING(64) NOT NULL,
  BuildNumber INT64,
  StartTime TIMESTAMP NOT NULL,
  Branch STRING(256) NOT NULL,
  ManifestCommitId STRING(64) NOT NULL,
  Milestone INT64,
  PlatformVersion STRING(64),
  WrittenAt TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (BuildId);

-- One row per config of a target of a build. Kind says which config it is:
-- 'ec-ro' and 'ec-rw' for the RO and RW Kconfigs of an EC target, 'ec' when a
-- target builds a single image, and 'coreboot', 'depthcharge' or 'libpayload'
-- for the Kconfig of a component of an AP image. Components holds the
-- Devicetree components of an EC target as a JSON array and ConfigHash points
-- at the config set.
CREATE TABLE BuildTargets (
  BuildId INT64 NOT NULL,
  Platform STRING(128) NOT NULL,
  Target STRING(128) NOT NULL,
  Kind STRING(32) NOT NULL,
  TarballUri STRING(MAX),
  ConfigHash STRING(64),
  Components JSON
) PRIMARY KEY (BuildId, Platform, Target, Kind),
  INTERLEAVE IN PARENT Builds ON DELETE CASCADE;

-- How a config of a target changed over the builds.
CREATE INDEX BuildTargetsByTarget
  ON BuildTargets(Target, Platform, Kind, BuildId DESC) STORING (ConfigHash);

-- A config set is complete once its ConfigSets row exists, because the row is
-- written after all of its ConfigSymbols rows.
CREATE TABLE ConfigSets (
  ConfigHash STRING(64) NOT NULL,
  SymbolCount INT64 NOT NULL,
  WrittenAt TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true)
) PRIMARY KEY (ConfigHash);

CREATE TABLE ConfigSymbols (
  ConfigHash STRING(64) NOT NULL,
  Name STRING(256) NOT NULL,
  Value STRING(MAX) NOT NULL
) PRIMARY KEY (ConfigHash, Name);

-- Which config sets have a symbol, and with which value.
CREATE INDEX ConfigSymbolsByName ON ConfigSymbols(Name) STORING (Value);

-- One row per symbol of every config of every target of every build, for
-- exploring. For example, the builds in which a target enabled CONFIG_FOO:
--   SELECT BuildId, Builder, Branch, StartTime FROM TargetConfigs
--   WHERE Target = 'krabby' AND Kind = 'ec-rw' AND Name = 'CONFIG_FOO'
--   ORDER BY BuildId DESC
CREATE VIEW TargetConfigs SQL SECURITY INVOKER AS
SELECT
  t.BuildId, b.Builder, b.Branch, b.StartTime, t.Platform, t.Target, t.Kind,
  s.Name, s.Value
FROM BuildTargets AS t
JOIN Builds AS b ON b.BuildId = t.BuildId
JOIN ConfigSymbols AS s ON s.ConfigHash = t.ConfigHash;
