# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api
from google.protobuf import json_format as jsonpb

from PB.chromiumos.builder_config import BuilderConfigs


class CrosInfraConfigTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the infra_config module."""

  # Number of seconds to wait on gitiles file download.
  gitiles_timeout_seconds = 3 * 60

  def builder_configs_step_test_data(self):
    """A fn that can be passed to step_test_data to generate BuilderConfigs."""
    builder_configs = """
            {
              "builderConfigs": [
                {
                  "id": {
                    "name": "amd64-generic-postsubmit",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": true
                  },
                  "artifacts": {
                    "prebuilts": "PRIVATE",
                    "artifact_types": ["IMAGE_ZIP"],
                    "artifacts_gs_bucket": "chromeos-image-archive",
                    "prebuilts_gs_bucket": "chromeos-prebuilt"
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "portage_profile": {
                      "profile": "generic_build"
                    },
                    "image_types": ["BASE", "TEST"],
                    "install_packages": "RUN",
                    "use_flags": [{"flag": "chrome_internal"}]
                  },
                  "unit_tests": {
                    "package_blacklist": [],
                    "ebuilds_run_spec": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "amd64-generic-cq",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": true
                  },
                  "artifacts": {
                    "prebuilts": "NONE",
                    "artifact_types": ["IMAGE_ZIP"]
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "install_packages": "RUN",
                    "apply_gerrit_changes": true,
                    "use_flags": [{"flag": "chrome_internal"}]
                  },
                  "unit_tests": {
                    "package_blacklist": [{
                      "package_name": "chromite",
                      "category": "chromeos-base",
                      "version": ""
                    }],
                    "ebuilds_run_spec": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "amd64-generic-snapshot",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": false
                  },
                  "artifacts": {
                    "prebuilts": "PUBLIC",
                    "artifact_types": [
                      "IMAGE_ZIP",
                      "AUTOTEST_FILES",
                      "TAST_FILES",
                      "PINNED_GUEST_IMAGES",
                      "EBUILD_LOGS",
                      "TEST_UPDATE_PAYLOAD"
                    ],
                    "prebuiltsGsBucket": "chromeos-prebuilt",
                    "artifactsGsBucket": "chromeos-image-archive"
                  },
                  "chrome": {
                    "internal": false
                  },
                  "build": {
                    "install_packages": "RUN",
                    "compile_tool_chain": false,
                    "apply_gerrit_changes": true
                  },
                  "unit_tests": {
                    "package_blacklist": [
                    ],
                    "ebuilds_run_spec": "RUN",
                    "emptySysroot": false
                  }
                },
                {
                  "id": {
                    "name": "arm-generic-cq",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": false
                  },
                  "artifacts": {
                    "prebuilts": "NONE"
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "install_packages": "RUN"
                  },
                  "unit_tests": {
                    "package_blacklist": [{
                      "package_name": "chromite",
                      "category": "chromeos-base",
                      "version": ""
                    }],
                    "ebuilds_run_spec": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "arm-generic-pointless-cq",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": false
                  },
                  "artifacts": {
                    "prebuilts": "NONE"
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "install_packages": "RUN"
                  },
                  "unit_tests": {
                    "package_blacklist": [{
                      "package_name": "chromite",
                      "category": "chromeos-base",
                      "version": ""
                    }],
                    "ebuilds_run_spec": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "staging-arm-generic-cq",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": false,
                    "environment": "STAGING"
                  },
                  "artifacts": {
                    "prebuilts": "NONE"
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "install_packages": "RUN"
                  },
                  "unit_tests": {
                    "package_blacklist": [{
                      "package_name": "chromite",
                      "category": "chromeos-base",
                      "version": ""
                    }],
                    "ebuilds_run_spec": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "amd64-generic-bisect",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": true
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "install_packages": "RUN_EXIT",
                    "apply_gerrit_changes": false
                  }
                },
                {
                  "id": {
                    "name": "arm-generic-postsubmit",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": false
                  },
                  "build": {
                    "install_packages": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "arm-generic-v42-buildtest-postsubmit",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": false
                  },
                  "build": {
                    "install_packages": "RUN_EXIT",
                    "packages": [{
                      "package_name": "chromeos-kernel",
                      "category": "syskernel",
                      "version": "4.19"
                    }]
                  }
                },
                {
                  "id": {
                    "name": "atlas-cq",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": true,
                    "broken_before": "2019-11-01T00:00:00Z"
                  },
                  "artifacts": {
                    "prebuilts": "NONE",
                    "artifact_types": ["IMAGE_ZIP"]
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "install_packages": "RUN",
                    "apply_gerrit_changes": true
                  },
                  "unit_tests": {
                    "package_blacklist": [{
                      "package_name": "chromite",
                      "category": "chromeos-base",
                      "version": ""
                    }],
                    "ebuilds_run_spec": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "target-baseline",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": false
                  },
                  "build": {
                    "install_packages": "RUN",
                    "apply_gerrit_changes": false
                  },
                  "unit_tests": {
                    "ebuilds_run_spec": "NO_RUN"
                  }
                },
                {
                  "id": {
                    "name": "grunt-postsubmit",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": false
                  },
                  "build": {
                    "install_packages": "RUN",
                    "apply_gerrit_changes": false
                  },
                  "unit_tests": {
                    "ebuilds_run_spec": "NO_RUN"
                  }
                },
                {
                  "id": {
                    "name": "grunt-unittest-only-postsubmit",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": false
                  },
                  "build": {
                    "install_packages": "RUN",
                    "apply_gerrit_changes": false
                  },
                  "unit_tests": {
                    "ebuilds_run_spec": "RUN_EXIT"
                  }
                },
                {
                  "id": {
                    "name": "toolchain-orchestrator",
                    "branch": "master",
                    "type": "TOOLCHAIN"
                  },
                  "general": {
                    "critical": true
                  },
                  "orchestrator": {
                    "children": [
                    ],
                    "gitiles_commit": {
                      "host": "chrome-internal",
                      "project": "chromeos/manifest-internal",
                      "ref": "refs/heads/snapshot"
                    },
                    "gerrit_changes": [{
                      "host": "chromium-review.googlesource.com",
                      "project": "chromiumos/overlays/chromiumos-overlay",
                      "change": 1394249,
                      "patchset": -1
                    }]
                  }
                },
                {
                  "id": {
                    "name": "postsubmit-orchestrator",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": true
                  },
                  "orchestrator": {
                    "children": [
                      "amd64-generic-postsubmit",
                      "arm-generic-postsubmit"
                    ]
                  }
                },
                {
                  "id": {
                    "name": "cq-orchestrator",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": true
                  },
                  "orchestrator": {
                    "children": [
                      "amd64-generic-cq",
                      "arm-generic-cq",
                      "arm-generic-pointless-cq",
                      "atlas-cq"
                    ]
                  }
                },
                {
                  "id": {
                    "name": "chromite-cq",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": true
                  }
                }
              ]
            }
          """
    configs = jsonpb.Parse(builder_configs, BuilderConfigs(),
                           ignore_unknown_fields=True)
    # Humans can edit the string above for test data, impl reads binary proto.
    return self.m.gitiles.make_encoded_file(configs.SerializeToString())
