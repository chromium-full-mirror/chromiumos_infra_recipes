# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility class of matching sources to test variants for auto exoneration v2"""
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional

from google.protobuf import json_format

from PB.go.chromium.org.luci.resultdb.proto.v1.invocation import Sources
from PB.go.chromium.org.luci.resultdb.proto.v1.resultdb import \
  QueryTestVariantsResponse
from PB.go.chromium.org.luci.resultdb.proto.v1.test_variant import TestVariant


class TestVariantMatcher:
  """Utility class that finds source position for test variants."""

  def __init__(self, query_func: Callable[[Optional[str]],
                                          QueryTestVariantsResponse]):
    """Initialize a new instance of TestVariantMatcher.

    Args:
      query_func: a wrapper function to the resultdb.QueryTestVariants API, with
        only page_token exposed.

    Returns:
      None
    """
    self._query_func = query_func

  def match_sources(self, test_variants: List[dict]) -> List[dict]:
    """Match test variants with sources.

    Args:
      test_variants: list of test variant dicts to be matched.

    Returns:
      a new list of test variant dicts that have sources populated. The list can
      be compared to the original to identify any missed matches.
    """
    response = self._query_func(None)
    variants_list = list(response.test_variants)
    sources_map = dict(response.sources.items())
    next_page_token = response.next_page_token

    while next_page_token:
      # Make another call to RDB with updated request
      new_response = self._query_func(next_page_token)

      # Update variants_list and sources_map
      variants_list.extend(new_response.test_variants)
      sources_map.update(dict(new_response.sources.items()))

      next_page_token = new_response.next_page_token

    return self._fine_match(test_variants, variants_list, sources_map)

  def _fine_match(self, test_variants: List[dict],
      variants_list: List[TestVariant], sources_map: Dict[str, Sources]) -> \
  List[dict]:
    """Match sources to test variants by inspecting individual variants.

    Args:
      test_variants: list of test variant dicts to be matched.
      variants_list: list of resultdb.v1.test_variant.TestVariant proto, which
        has a sources_id to be used for lookup.
      sources_map: a dict of source_id to resultdb.v1.invocation.Sources proto.

    Returns:
      a new list of test variant dicts that have sources populated. The list can
      be compared to the original to identify any missed matches.
    """
    matched = []
    index = {}
    # Build an index from protos
    for variant in variants_list:
      key = self._get_variant_key(variant)
      index[key] = sources_map[variant.sources_id]

    # Look up sources from the index and populate for each variant dict
    for variant_dict in test_variants:
      variant_pb = json_format.ParseDict(variant_dict, TestVariant(),
                                         ignore_unknown_fields=True)
      key = self._get_variant_key(variant_pb)
      sources = index.get(key, None)
      if sources:
        variant_dict['sources'] = json_format.MessageToDict(sources)
        matched.append(variant_dict)

    return matched

  def _get_variant_key(self, variant: TestVariant) -> int:
    """Derive a key for the variant. Only use test_id and variant fields."""
    # Create a new proto with only required fields for the key.
    variant_pb = TestVariant(test_id=variant.test_id, variant=variant.variant)
    # deterministic is required to sort map keys.
    return hash(variant_pb.SerializeToString(deterministic=True))
