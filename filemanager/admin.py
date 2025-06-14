# filemanager/admin.py - Complete simplified admin

from django.contrib import admin
from django.contrib.auth.models import Group
from django.contrib.auth.admin import GroupAdmin
from django.utils.html import format_html
from django.urls import reverse
from django.core.exceptions import ValidationError
from django import forms
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


# Custom admin form for Folder
class FolderAdminForm(forms.ModelForm):
    """Custom form for Folder admin - simplified"""
    
    class Meta:
        model = Folder
        exclude = ['created_by']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add help text
        self.fields['access_type'].help_text = (
            "Private: Only you can access | "
            "Public: Everyone can access | "
            "Group: Only group members can access"
        )
        
        self.fields['group'].help_text = "Only required for 'Group Access' folders"
    
    def clean(self):
        """Custom validation for access type and group"""
        cleaned_data = super().clean()
        access_type = cleaned_data.get('access_type')
        group = cleaned_data.get('group')
        
        if access_type == 'group' and not group:
            raise ValidationError("Group is required when access type is 'Group Access'")
        
        if access_type != 'group' and group:
            # Clear group if not needed
            cleaned_data['group'] = None
        
        return cleaned_data


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    """Simplified admin interface for Folder management"""
    
    form = FolderAdminForm
    
    list_display = [
        'name',
        'access_type_display', 
        'access_details',
        'parent_folder', 
        'created_by', 
        'document_count',
        'subfolder_count',
        'created_at'
    ]
    
    list_filter = [
        'access_type',
        'group', 
        'created_at',
        'parent_folder'
    ]
    
    search_fields = [
        'name', 
        'description',
        'created_by__username',
        'created_by__email',
        'group__name'
    ]
    
    readonly_fields = [
        'created_at',
        'created_by_display',
        'document_count', 
        'subfolder_count', 
        'full_path_display',
        'access_description_display'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'full_path_display')
        }),
        ('Access Control', {
            'fields': ('access_type', 'group', 'access_description_display'),
            'description': 'Configure who can access this folder'
        }),
        ('Organization', {
            'fields': ('parent_folder',)
        }),
        ('Metadata', {
            'fields': ('created_by_display', 'created_at'),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('document_count', 'subfolder_count'),
            'classes': ('collapse',)
        }),
    )
    
    def created_by_display(self, obj):
        """Show who created the folder (readonly)"""
        if obj.created_by:
            return f"{obj.created_by.username} ({obj.created_by.get_full_name() or obj.created_by.email})"
        return "Unknown"
    created_by_display.short_description = 'Created By'

    def access_type_display(self, obj):
        """UPDATED: Clean access type display without colors or confusing text"""
        # Simple text display without colors or user-specific language
        display_text = obj.get_access_type_display()
        
        # Remove the confusing "(Only Me)" type text and just show the type
        type_mapping = {
            'Private (Only Me)': 'Private',
            'Public (Everyone in Company)': 'Public',
            'Group Access': 'Group'
        }
        
        clean_text = type_mapping.get(display_text, display_text)
        
        # Return plain text without any styling
        return clean_text
    
    access_type_display.short_description = 'Access Type'
    access_type_display.admin_order_field = 'access_type'
    
    def access_details(self, obj):
        """Show specific access details - updated for admin context"""
        if obj.access_type == 'private':
            return f"Owner: {obj.created_by.username if obj.created_by else 'Unknown'}"
        elif obj.access_type == 'public':
            return "All users"
        elif obj.access_type == 'group':
            if obj.group:
                member_count = obj.group.user_set.count()
                return f"Group: {obj.group.name} ({member_count} members)"
            return "No group assigned"
        return "Unknown"
    
    access_details.short_description = 'Access Details'
    
    def document_count(self, obj):
        """Document count with link"""
        count = obj.documents.count()
        if count > 0:
            url = reverse('admin:filemanager_uploadeddocument_changelist')
            return format_html(
                '<a href="{}?folder__id__exact={}">{} documents</a>',
                url, obj.id, count
            )
        return '0 documents'
    
    document_count.short_description = 'Documents'
    
    def subfolder_count(self, obj):
        """Subfolder count with link"""
        count = obj.children.count()
        if count > 0:
            url = reverse('admin:filemanager_folder_changelist')
            return format_html(
                '<a href="{}?parent_folder__id__exact={}">{} subfolders</a>',
                url, obj.id, count
            )
        return '0 subfolders'
    
    subfolder_count.short_description = 'Subfolders'
    
    def full_path_display(self, obj):
        """Full path with access info"""
        return obj.get_full_path_with_access()
    
    full_path_display.short_description = 'Full Path'
    
    def access_description_display(self, obj):
        """Human-readable access description"""
        return obj.get_access_description()
    
    access_description_display.short_description = 'Access Description'
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """FIXED: Show all folders for parent folder selection in admin"""
        if db_field.name == "parent_folder":
            # In admin, show ALL folders (not filtered by user access)
            kwargs["queryset"] = Folder.objects.all().select_related('group', 'created_by').order_by('name')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def get_queryset(self, request):
        """Optimize queries"""
        return super().get_queryset(request).select_related(
            'group', 'parent_folder', 'created_by'
        ).prefetch_related('documents', 'children')
    
    def save_model(self, request, obj, form, change):
        """Auto-populate created_by for new folders"""
        if not change:  # New object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    actions = ['make_public', 'make_private']
    
    def make_public(self, request, queryset):
        """Admin action to make folders public - with hierarchy-aware processing"""
        count = 0
        errors = []
        
        # FIXED: Sort folders by hierarchy depth (parents first)
        folders_by_depth = []
        for folder in queryset:
            depth = 0
            current = folder.parent_folder
            while current:
                depth += 1
                current = current.parent_folder
            folders_by_depth.append((depth, folder))
        
        # Sort by depth (shallowest/parents first)
        folders_by_depth.sort(key=lambda x: x[0])
        
        for depth, folder in folders_by_depth:
            if folder.access_type != 'public':
                try:
                    folder.access_type = 'public'
                    folder.group = None
                    folder.full_clean()
                    folder.save()
                    count += 1
                except ValidationError as e:
                    errors.append(f"'{folder.name}': {'; '.join(e.messages)}")
        
        if count > 0:
            self.message_user(request, f'{count} folders made public.')
        if errors:
            error_msg = "Some folders could not be changed: " + " | ".join(errors[:3])
            if len(errors) > 3:
                error_msg += f" and {len(errors) - 3} more errors."
            self.message_user(request, error_msg, level='ERROR')
    
    make_public.short_description = 'Make selected folders public'
    
    def make_private(self, request, queryset):
        """Admin action to make folders private - with hierarchy-aware processing"""
        count = 0
        errors = []
        
        # FIXED: Sort folders by hierarchy depth (children first for private)
        folders_by_depth = []
        for folder in queryset:
            depth = 0
            current = folder.parent_folder
            while current:
                depth += 1
                current = current.parent_folder
            folders_by_depth.append((depth, folder))
        
        # Sort by depth (deepest/children first for private)
        folders_by_depth.sort(key=lambda x: x[0], reverse=True)
        
        for depth, folder in folders_by_depth:
            if folder.access_type != 'private':
                try:
                    folder.access_type = 'private'
                    folder.group = None
                    folder.full_clean()
                    folder.save()
                    count += 1
                except ValidationError as e:
                    errors.append(f"'{folder.name}': {'; '.join(e.messages)}")
        
        if count > 0:
            self.message_user(request, f'{count} folders made private.')
        if errors:
            error_msg = "Some folders could not be changed: " + " | ".join(errors[:3])
            if len(errors) > 3:
                error_msg += f" and {len(errors) - 3} more errors."
            self.message_user(request, error_msg, level='ERROR')
    
    make_private.short_description = 'Make selected folders private'


@admin.register(UploadedDocument)
class UploadedDocumentAdmin(admin.ModelAdmin):
    """Admin interface for UploadedDocument management"""
    list_display = [
        'title',
        'file_type',
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
            'fields': ('folder',)
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
        
        self.message_user(request, f'{count} documents marked for reprocessing.')
    reprocess_documents.short_description = 'Reprocess selected documents'
    
    def mark_as_pending(self, request, queryset):
        """Admin action to mark documents as pending"""
        updated = queryset.update(processing_status='pending')
        self.message_user(request, f'{updated} documents marked as pending.')
    mark_as_pending.short_description = 'Mark as pending'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'folder', 'uploaded_by'
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