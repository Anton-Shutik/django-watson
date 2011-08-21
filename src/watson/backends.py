"""Search backends used by django-watson."""

from abc import ABCMeta, abstractmethod

from django.conf import settings
from django.utils.importlib import import_module
from django.core.exceptions import ImproperlyConfigured
from django.contrib.contenttypes.models import ContentType
from django.db import models, connection
from django.db.models import Q

from watson.models import SearchEntry


class SearchBackend(object):

    """Base class for all search backends."""

    __metaclass__ = ABCMeta
    
    @abstractmethod
    def do_install(self):
        """Generates the SQL needed to install django-watson."""
        raise NotImplementedError
        
    @abstractmethod
    def do_search(self, queryset, search_text):
        """Filters the given queryset according the the search logic for this backend."""
        raise NotImplementedError
    
    @abstractmethod
    def save_search_entry(self, obj, search_entry, weighted_search_text):
        """Saves the given search entry in the database."""
        raise NotImplementedError
        
    def search(self, search_text, models=None, exclude=None):
        """Performs a search using the given text, returning a queryset of SearchEntry."""
        queryset = SearchEntry.objects.all()
        # Add in a model limiter.
        if models:
            content_types = [
                ContentType.objects.get_for_model(model)
                for model in models
            ]
            queryset = queryset.filter(content_type__in=content_types)
        if exclude:
            content_types = [
                ContentType.objects.get_for_model(model)
                for model in exclude
            ]
            queryset = queryset.exclude(content_type__in=content_types)
        # Perform the backend-specific full text match.
        queryset = self.do_search(queryset, search_text)
        return queryset
        
        
class PostgresSearchBackend(SearchBackend):

    """A search backend that uses native PostgreSQL full text indices."""
    
    def do_install(self):
        """Generates the PostgreSQL specific SQL code to install django-watson."""
        connection.cursor().execute("""
            ALTER TABLE "watson_searchentry" ADD COLUMN "search_tsv" tsvector NOT NULL;

            CREATE INDEX "watson_searchentry_search_tsv" ON "watson_searchentry" USING gin("search_tsv");
        """)
        
    def save_search_entry(self, obj, search_entry, weighted_search_text):
        """Saves the search entry."""        
        sql_params = [
            search_entry.object_id,
            search_entry.object_id_int,
            search_entry.content_type_id,
            search_entry.meta_encoded,
            u" ".join(weighted_search_text[:1]),
            u" ".join(weighted_search_text[1:2]),
            u" ".join(weighted_search_text[2:3]),
            u" ".join(weighted_search_text[3:]),
        ]
        if search_entry.id is None:
            # Perform a raw insert.
            sql_str = u"""
                INSERT INTO
                    "watson_searchentry"
                (
                    "object_id",
                    "object_id_int",
                    "content_type_id",
                    "meta_encoded",
                    "search_tsv"
                ) VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    (
                        setweight(to_tsvector(%s), 'A') ||
                        setweight(to_tsvector(%s), 'B') ||
                        setweight(to_tsvector(%s), 'C') ||
                        setweight(to_tsvector(%s), 'D')
                    )
                )"""
        else:
            # Perform a raw update.
            sql_str = u"""
                UPDATE
                    "watson_searchentry"
                SET
                    "object_id" = %s,
                    "object_id_int" = %s,
                    "content_type_id" = %s,
                    "meta_encoded" = %s,
                    "search_tsv" = (
                        setweight(to_tsvector(%s), 'A') ||
                        setweight(to_tsvector(%s), 'B') ||
                        setweight(to_tsvector(%s), 'C') ||
                        setweight(to_tsvector(%s), 'D')
                    )
                WHERE
                    "id" = %s
                """
            sql_params.append(search_entry.id)
        # Perform the query.
        connection.cursor().execute(sql_str, sql_params)
        
    def do_search(self, queryset, search_text):
        """Performs the full text search."""
        return queryset.extra(
            select = {
                "rank": 'ts_rank_cd("search_tsv", plainto_tsquery(%s))',
            },
            select_params = (search_text,),
            where = ('"search_tsv" @@ plainto_tsquery(%s)',),
            params = (search_text,),
            order_by = ("-rank",),
        )
        
        
class DumbSearchBackend(SearchBackend):

    """
    A search backend that uses a dumb ILIKE search to find results.
    
    This is fine for debugging locally, but rubbish for production.
    """
    
    def do_install(self):
        """Just create a dumb text column."""
        from south.db import db
        db.add_column(SearchEntry._meta.db_table, "search_text", models.TextField(default=""), keep_default=False)
        
    def do_search(self, queryset, search_text):
        """Performs the dumb search."""
        words = search_text.lower().split()
        sql_str = u" OR ".join(
            u"({search_text} LIKE %s)".format(
                search_text = connection.ops.quote_name("search_text"),
            )
            for _ in words
        )
        sql_params = [
            "%" + connection.ops.prep_for_like_query(word) + "%"
            for word in words
        ]
        return queryset.extra(
            where = (sql_str,),
            params = sql_params,
        )
        
    def save_search_entry(self, obj, search_entry, weighted_search_text):
        """Saves the search entry."""
        # Consolidate the search entry data.
        search_text = u" ".join(weighted_search_text).lower()
        # Hijack the save with raw SQL!
        sql_params = [
            search_entry.object_id,
            search_entry.object_id_int,
            search_entry.content_type_id,
            search_entry.meta_encoded,
            search_text,
        ]
        if search_entry.pk is None:
            # Perform a raw insert.
            sql_str = u"""
                INSERT INTO
                    {watson_searchentry}
                (
                    {object_id},
                    {object_id_int},
                    {content_type_id},
                    {meta_encoded},
                    {search_text}
                ) VALUES (
                    %s, %s, %s, %s, %s
                )"""
        else:
            # Perform a raw update.
            sql_str = u"""
                UPDATE
                    {watson_searchentry}
                SET
                    {object_id} = %s,
                    {object_id_int} = %s,
                    {content_type_id} = %s,
                    {meta_encoded} = %s,
                    {search_text} = %s
                WHERE
                    {id} = %s
                """
            sql_params.append(search_entry.id)
        # Perform the query.
        sql_str = sql_str.format(**dict(
            (column_name, connection.ops.quote_name(column_name))
            for column_name in
            ("watson_searchentry", "object_id", "object_id_int", "content_type_id", "meta_encoded", "search_text", "id")
        ))
        connection.cursor().execute(sql_str, sql_params)
        
        
class AdaptiveSearchBackend(SearchBackend):

    """
    A search backend that guesses the correct search backend based on the
    DATABASES["default"] settings.
    """
    
    def __new__(cls):
        """Guess the correct search backend and initialize it."""
        database_engine = settings.DATABASES["default"]["ENGINE"]
        if database_engine.endswith("postgresql_psycopg2") or database_engine.endswith("postgresql"):
            return PostgresSearchBackend()
        else:
            return DumbSearchBackend()
            

# The cache for the initialized backend.
_backend_cache = None


def get_backend():
    """Initializes and returns the search backend."""
    global _backend_cache
    # Try to use the cached backend.
    if _backend_cache is not None:
        return _backend_cache
    # Load the backend class.
    backend_name = getattr(settings, "WATSON_BACKEND", "watson.backends.AdaptiveSearchBackend")
    backend_module_name, backend_cls_name = backend_name.rsplit(".", 1)
    backend_module = import_module(backend_module_name)
    try:
        backend_cls = getattr(backend_module, backend_cls_name)
    except AttributeError:
        raise ImproperlyConfigured("Could not find a class named {backend_module_name!r} in {backend_cls_name!r}".format(
            backend_module_name = backend_module_name,
            backend_cls_name = backend_cls_name,
        ))
    # Initialize the backend.
    backend = backend_cls()
    _backend_cache = backend
    return backend