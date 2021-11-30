# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for adding provenenace to generated artifacts."""

from recipe_engine import recipe_api


class ProvenanceApi(recipe_api.RecipeApi):
  """Apis for generating a signed provenance for created artifacts."""

  def __init__(self, properties, *args, **kwargs):
    super(ProvenanceApi, self).__init__(*args, **kwargs)
    self._key_path = properties.key_path

  def generate_provenance(self, file_paths, recipe):
    """Generate BCID provenances for a list of artifacts.

        Args:
          file_paths (List[str]): the location of artifacts to generate an
              attestation for.
          recipe (str): the name of the recipe that this build is running.

        Returns:
          (List[str]): the location of the attestations on disk.
        """
    attestations = []
    provenance_manifest = {
        "recipe": recipe,
        "exp": 0,
        "topLevelSource": {},
    }

    with self.m.step.nest("generate attestations") as pres:
      for file_path in file_paths:
        file_hash = self.m.file.file_hash(file_path, test_data="deadbeef")
        provenance_manifest["subjectHash"] = file_hash
        temp_dir = self.m.path.mkdtemp("tmp")
        manifest_path = temp_dir.join("manifest.json")
        self.m.file.write_text(
            "Provenance manifest",
            manifest_path,
            self.m.json.dumps(provenance_manifest),
        )
        provenance_path = file_path + ".attestation"
        self.m.provenance.generate(self._key_path, manifest_path,
                                   provenance_path)
        attestations.append(provenance_path)

        pres.logs["attestations %s" % file_paths] = attestations
      pres.step_text = "Generated attestations for {} files".format(
          len(file_paths))

    return attestations
