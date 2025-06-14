from django.contrib import admin
from django.contrib.auth.models import Group
from django.contrib.auth.admin import GroupAdmin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import Folder, UploadedDocument, DocumentChunk, ProcessingLog


# Customize the built-in Group admin to show member count
class CustomGroupAdmin(GroupAdmin):
    """Enhanced Group admin with member count"""
    list_display = ['name', 'member_count', 'permissions_count']
    search_fields = ['name']
    
    def member_count(self, obj):
        return obj.user_set.count()
    member_count.short_description = 'Members'
    member_count.admin_order_field = 'user_set__count'
    
    def permissions_count(self, obj):
        return obj.permissions.count()
    permissions_count.short_description = 'Permissions'

# Unregister the default Group admin and register our custom one
admin.site.unregister(Group)
admin.site.register(Group, CustomGroupAdmin)


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    """Admin interface for Folder management"""
    list_display = [
        'name', 
        'group', 
        'parent_folder', 
        'created_by', 
        'document_count',
        'subfolder_count',
        'created_at'
    ]
    list_filter = [
        'group', 
        'created_at',
        'parent_folder'
    ]
    search_fields = [
        'name', 
        'description',
        'created_by__username',
        'created_by__email'
    ]
    raw_id_fields = ['parent_folder', 'created_by']
    readonly_fields = ['created_at', 'document_count', 'subfolder_count', 'full_path']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'full_path')
        }),
        ('Organization', {
            'fields': ('parent_folder', 'group')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at'),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('document_count', 'subfolder_count'),
            'classes': ('collapse',)
        }),
    )
    
    def document_count(self, obj):
        count = obj.documents.count()
        if count > 0:
            url = reverse('admin:documents_uploadeddocument_changelist')
            return format_html(
                '<a href="{}?folder__id__exact={}">{} documents</a>',
                url, obj.id, count
            )
        return '0 documents'
    document_count.short_description = 'Documents'
    
    def subfolder_count(self, obj):
        count = obj.children.count()
        if count > 0:
            url = reverse('admin:documents_folder_changelist')
            return format_html(
                '<a href="{}?parent_folder__id__exact={}">{} subfolders</a>',
                url, obj.id, count
            )
        return '0 subfolders'
    subfolder_count.short_description = 'Subfolders'
    
    def full_path(self, obj):
        return obj.get_path()
    full_path.short_description = 'Full Path'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'group', 'parent_folder', 'created_by'
        ).prefetch_related('documents', 'children')


@admin.register(UploadedDocument)
class UploadedDocumentAdmin(admin.ModelAdmin):
    """Admin interface for UploadedDocument management"""
    list_display = [
        'title',
        'file_type',
        'group',
        'folder',
        'processing_status',
        'uploaded_by',
        'file_size_display',
        'chunk_count',
        'uploaded_at'
    ]
    list_filter = [
        'file_type',
        'processing_status',
        'group',
        'uploaded_at',
        'processed_at'
    ]
    search_fields = [
        'title',
        'original_filename',
        'uploaded_by__username',
        'uploaded_by__email'
    ]
    raw_id_fields = ['folder', 'uploaded_by']
    readonly_fields = [
        'original_filename',
        'file_size',
        'file_size_display',
        'mime_type',
        'llamaindex_doc_id',
        'chunk_count',
        'uploaded_at',
        'processed_at',
        'file_preview'
    ]
    
    fieldsets = (
        ('File Information', {
            'fields': ('title', 'file', 'file_preview', 'original_filename')
        }),
        ('Organization', {
            'fields': ('folder', 'group')
        }),
        ('File Details', {
            'fields': ('file_type', 'file_size_display', 'mime_type'),
            'classes': ('collapse',)
        }),
        ('Processing', {
            'fields': ('processing_status', 'llamaindex_doc_id', 'chunk_count', 'processed_at')
        }),
        ('Metadata', {
            'fields': ('uploaded_by', 'uploaded_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['reprocess_documents', 'mark_as_pending']
    
    def file_size_display(self, obj):
        return obj.get_file_size_display()
    file_size_display.short_description = 'File Size'
    
    def file_preview(self, obj):
        if obj.file:
            if obj.file_type == 'image':
                return format_html(
                    '<img src="{}" style="max-width: 200px; max-height: 200px;" />',
                    obj.file.url
                )
            else:
                return format_html(
                    '<a href="{}" target="_blank">Download {}</a>',
                    obj.file.url, obj.original_filename
                )
        return "No file"
    file_preview.short_description = 'File Preview'
    
    def reprocess_documents(self, request, queryset):
        """Admin action to reprocess selected documents"""
        count = 0
        for doc in queryset:
            if doc.is_processable_by_llamaindex():
                doc.processing_status = 'pending'
                doc.save()
                count += 1
                # TODO: Trigger background processing
                # process_document_and_update_user_vectorstore.delay(doc.id, doc.uploaded_by.id)
        
        self.message_user(request, f'{count} documents marked for reprocessing.')
    reprocess_documents.short_description = 'Reprocess selected documents'
    
    def mark_as_pending(self, request, queryset):
        """Admin action to mark documents as pending"""
        updated = queryset.update(processing_status='pending')
        self.message_user(request, f'{updated} documents marked as pending.')
    mark_as_pending.short_description = 'Mark as pending'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'group', 'folder', 'uploaded_by'
        )


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    """Admin interface for DocumentChunk management"""
    list_display = [
        'document',
        'chunk_index',
        'chunk_preview',
        'llamaindex_node_id',
        'created_at'
    ]
    list_filter = [
        'created_at',
        'document__file_type',
        'document__processing_status'
    ]
    search_fields = [
        'document__title',
        'chunk_text',
        'llamaindex_node_id'
    ]
    raw_id_fields = ['document']
    readonly_fields = ['chunk_preview_full', 'metadata_display', 'created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('document', 'chunk_index', 'llamaindex_node_id')
        }),
        ('Content', {
            'fields': ('chunk_text', 'chunk_preview_full')
        }),
        ('Metadata', {
            'fields': ('metadata_display', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    
    def chunk_preview(self, obj):
        preview = obj.chunk_text[:100]
        if len(obj.chunk_text) > 100:
            preview += "..."
        return preview
    chunk_preview.short_description = 'Preview'
    
    def chunk_preview_full(self, obj):
        return format_html('<pre>{}</pre>', obj.chunk_text[:500])
    chunk_preview_full.short_description = 'Full Preview (500 chars)'
    
    def metadata_display(self, obj):
        if obj.metadata:
            import json
            return format_html('<pre>{}</pre>', json.dumps(obj.metadata, indent=2))
        return "No metadata"
    metadata_display.short_description = 'Metadata (JSON)'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('document')


@admin.register(ProcessingLog)
class ProcessingLogAdmin(admin.ModelAdmin):
    """Admin interface for ProcessingLog management"""
    list_display = [
        'document',
        'status',
        'message_preview',
        'timestamp'
    ]
    list_filter = [
        'status',
        'timestamp'
    ]
    search_fields = [
        'document__title',
        'message',
        'error_details'
    ]
    raw_id_fields = ['document']
    readonly_fields = ['timestamp', 'message_full', 'error_details_full']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('document', 'status', 'timestamp')
        }),
        ('Details', {
            'fields': ('message', 'message_full')
        }),
        ('Error Information', {
            'fields': ('error_details', 'error_details_full'),
            'classes': ('collapse',)
        }),
    )
    
    def message_preview(self, obj):
        preview = obj.message[:50]
        if len(obj.message) > 50:
            preview += "..."
        return preview
    message_preview.short_description = 'Message'
    
    def message_full(self, obj):
        return format_html('<pre>{}</pre>', obj.message)
    message_full.short_description = 'Full Message'
    
    def error_details_full(self, obj):
        if obj.error_details:
            return format_html('<pre>{}</pre>', obj.error_details)
        return "No error details"
    error_details_full.short_description = 'Full Error Details'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('document')


# Customize admin site headers
admin.site.site_header = "Document RAG System Administration"
admin.site.site_title = "RAG Admin"
admin.site.index_title = "Welcome to Document RAG System Administration"