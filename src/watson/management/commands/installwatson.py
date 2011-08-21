"""Creates the database indices needed by django-watson."""

from django.core.management.base import NoArgsCommand
from django.db import transaction
from django.core.management import call_command

from watson.registration import get_backend


class Command(NoArgsCommand):

    help = "Creates the database indices needed by django-watson."
    
    @transaction.commit_on_success
    def handle_noargs(self, **options):
        """Runs the management command."""
        backend = get_backend()
        install_sql = backend.do_install()
        call_command("rebuildwatson")