from django.db import models
from django.contrib.auth.models import User, Group  # Use Django's built-in Group
from django.core.exceptions import ValidationError
import os
from pathlib import Path
import mimetypes


class Folder(models.Model):
    """Simple nested folder structure with Django Group permissions"""
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    parent_folder = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE,
        null=True, 
        blank=True,
        related_name='children'
    )
    
    # Auto-populated from request.user
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Use Django's built-in Group system
    group = models.ForeignKey(
        Group, 
        on_delete=models.CASCADE,
    )

    class Meta:
        verbose_name_plural = "Folders"
        unique_together = ['name', 'parent_folder', 'group']
    
    def __str__(self):
        if self.parent_folder:
            return f"{self.parent_folder} / {self.name}"
        return f"{self.name} ({self.group.name})"
    
    def clean(self):
        """Prevent circular references"""
        if self.parent_folder:
            current = self.parent_folder
            for _ in range(10):
                if current == self:
                    raise ValidationError("Cannot create circular folder reference")
                if current.parent_folder:
                    current = current.parent_folder
                else:
                    break
    
    def get_path(self):
        """Get folder path like 'Root/Sub1/Sub2'"""
        path = [self.name]
        current = self.parent_folder
        while current:
            path.insert(0, current.name)
            current = current.parent_folder
        return " / ".join(path)
    
    def user_can_access(self, user):
        """Check if user can access this folder"""
        return self.group in user.groups.all()


class UploadedDocument(models.Model):
    """Simplified document model - auto-populated user from request"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    # User inputs (only these are required)
    file = models.FileField(upload_to='documents/%Y/%m/')
    folder = models.ForeignKey(
        Folder, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='documents'
    )
    
    # Auto-populated from request.user (no user input needed)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    # Auto-generated fields (filled automatically on save)
    title = models.CharField(max_length=255, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    file_type = models.CharField(max_length=20, blank=True)
    file_size = models.BigIntegerField(default=0)
    mime_type = models.CharField(max_length=100, blank=True)
    
    # Processing tracking
    processing_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    # LlamaIndex integration
    llamaindex_doc_id = models.CharField(max_length=255, blank=True, unique=True)
    chunk_count = models.IntegerField(default=0)
    
    # Use Django's built-in Group system
    group = models.ForeignKey(
        Group, 
        on_delete=models.CASCADE,
        help_text="Controls who can see this document (inherited from folder or set directly)"
    )
    
    class Meta:
        ordering = ['-uploaded_at']
    
    def __str__(self):
        return self.title or self.original_filename
    
    def save(self, *args, **kwargs):
        """Auto-populate fields when saving"""
        if self.file and not self.title:
            self.original_filename = os.path.basename(self.file.name)
            self.title = Path(self.original_filename).stem.replace('_', ' ').replace('-', ' ').title()
            self.file_size = self.file.size
            self.mime_type = mimetypes.guess_type(self.file.name)[0] or ''
            self.file_type = self._detect_file_type()
        
        # Auto-set group from folder if not set
        if self.folder and not self.group_id:
            self.group = self.folder.group
        
        super().save(*args, **kwargs)
    
    def _detect_file_type(self):
        """Auto-detect file type from extension"""
        if not self.file:
            return 'unknown'
        
        ext = Path(self.file.name).suffix.lower().lstrip('.')
        
        type_mapping = {
            'pdf': 'pdf',
            'doc': 'docx', 'docx': 'docx',
            'ppt': 'pptx', 'pptx': 'pptx', 
            'xls': 'xlsx', 'xlsx': 'xlsx',
            'txt': 'txt',
            'md': 'markdown',
            'csv': 'csv',
            'json': 'json',
            'xml': 'xml',
            'html': 'html', 'htm': 'html',
            'py': 'python',
            'js': 'javascript',
            'java': 'java',
            'cpp': 'cpp', 'c': 'cpp', 'cc': 'cpp',
            'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'gif': 'image',
            'mp3': 'audio', 'wav': 'audio', 'mp4': 'video', 'avi': 'video',
        }
        
        return type_mapping.get(ext, 'other')
    
    def get_file_size_display(self):
        """Human readable file size"""
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    
    def is_processable_by_llamaindex(self):
        """Check if LlamaIndex can process this file type"""
        processable_types = [
            'pdf', 'docx', 'pptx', 'xlsx', 'txt', 'markdown', 
            'csv', 'json', 'xml', 'html', 'python', 'javascript'
        ]
        return self.file_type in processable_types
    
    def user_can_access(self, user):
        """Check if user can access this document"""
        return self.group in user.groups.all()


class DocumentChunk(models.Model):
    """Store text chunks created by LlamaIndex"""
    
    document = models.ForeignKey(
        UploadedDocument, 
        on_delete=models.CASCADE, 
        related_name='chunks'
    )
    
    chunk_text = models.TextField()
    chunk_index = models.IntegerField()
    
    # LlamaIndex metadata
    llamaindex_node_id = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['chunk_index']
        unique_together = ['document', 'chunk_index']
    
    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.document.title}"


class ProcessingLog(models.Model):
    """Simple logging for document processing"""
    
    STATUS_CHOICES = [
        ('info', 'Info'),
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ]
    
    document = models.ForeignKey(
        UploadedDocument, 
        on_delete=models.CASCADE, 
        related_name='logs'
    )
    
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    message = models.TextField()
    error_details = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.document.title} - {self.status}: {self.message[:50]}"


# Helper functions for user vectorstore management
class UserVectorstoreManager:
    """Manage per-user vectorstores containing all their accessible content"""
    
    @staticmethod
    def get_user_vectorstore_name(user):
        """Get unique vectorstore name for user"""
        return f"user_{user.id}_vectorstore"
    
    @staticmethod
    def get_user_accessible_documents(user):
        """Get all documents user can access across all their groups"""
        user_groups = user.groups.all()
        return UploadedDocument.objects.filter(
            group__in=user_groups,
            processing_status='completed'
        )
    
    @staticmethod
    def should_rebuild_user_vectorstore(user):
        """Check if user's vectorstore needs rebuilding"""
        # Simple check: if any document was processed after last rebuild
        # You could store last_rebuild_time in user profile
        return True  # For now, always allow rebuild