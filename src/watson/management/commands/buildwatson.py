"""Rebuilds the database indices needed by django-watson."""

from django.core.management.base import NoArgsCommand
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from watson.registration import SearchEngine
from watson.models import SearchEntry


class Command(NoArgsCommand):

    help = "Rebuilds the database indices needed by django-watson."
    
    @transaction.commit_on_success
    def handle_noargs(self, **options):
        """Runs the management command."""
        verbosity = int(options.get("verbosity", 1))
        for engine_slug, search_engine in SearchEngine.get_created_engines():
            registered_models = search_engine.get_registered_models()
            # Rebuild the index for all registered models.
            refreshed_model_count = 0
            for model in registered_models:
                for obj in model._default_manager.all().iterator():
                    search_engine.update_obj_index(obj)
                    refreshed_model_count += 1
            if verbosity >= 2:
                print u"Refreshed {refreshed_model_count} search entry(s) in {engine_slug!r} search engine.".format(
                    refreshed_model_count = refreshed_model_count,
                    engine_slug = engine_slug,
                )
            # Clean out any search entries that exist for stale content types.
            valid_content_types = [ContentType.objects.get_for_model(model) for model in registered_models]
            stale_entries = SearchEntry.objects.filter(
                engine_slug = engine_slug,
            ).exclude(
                content_type__in = valid_content_types
            )
            stale_entry_count = stale_entries.count()
            if stale_entry_count > 0:
                stale_entries.delete()
            if verbosity >= 2:
                print u"Deleted {stale_entry_count} stale search entry(s) in {engine_slug!r} search engine.".format(
                    stale_entry_count = stale_entry_count,
                    engine_slug = engine_slug,
                )