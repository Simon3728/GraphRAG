from django.db import models
from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError
import os
from pathlib import Path
import mimetypes


class Folder(models.Model):
    """Folder structure with flexible access control and parent-child validation"""
    
    ACCESS_TYPE_CHOICES = [
        ('private', 'Private (Only Me)'),
        ('public', 'Public (Everyone in Company)'),
        ('group', 'Group Access'),
    ]
    
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
    
    # Access control system
    access_type = models.CharField(
        max_length=10, 
        choices=ACCESS_TYPE_CHOICES, 
        default='private',
        help_text="Who can access this folder"
    )
    
    # Only required when access_type='group'
    group = models.ForeignKey(
        Group, 
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Required only for group access"
    )

    class Meta:
        verbose_name_plural = "Folders"
        constraints = [
            # For group folders: name + parent + access_type + group must be unique
            models.UniqueConstraint(
                fields=['name', 'parent_folder', 'access_type', 'group'],
                condition=models.Q(access_type='group'),
                name='unique_group_folder'
            ),
            # For private folders: name + parent + access_type must be unique
            models.UniqueConstraint(
                fields=['name', 'parent_folder', 'access_type'],
                condition=models.Q(access_type='private'),
                name='unique_private_folder'
            ),
            # For public folders: name + parent + access_type must be unique
            models.UniqueConstraint(
                fields=['name', 'parent_folder', 'access_type'],
                condition=models.Q(access_type='public'),
                name='unique_public_folder'
            ),
        ]
    
    def __str__(self):
        access_info = {
            'private': f"(Private - {self.created_by.username if self.created_by else 'Unknown'})",
            'public': "(Public)",
            'group': f"({self.group.name if self.group else 'No Group'})"
        }
        
        if self.parent_folder:
            return f"{self.parent_folder} / {self.name} {access_info.get(self.access_type, '')}"
        return f"{self.name} {access_info.get(self.access_type, '')}"
    
    def clean(self):
        """Enhanced validation for folder configuration and parent-child relationships"""
        # Prevent circular references
        if self.parent_folder:
            current = self.parent_folder
            for _ in range(10):  # Prevent infinite loops
                if current == self:
                    raise ValidationError("Cannot create circular folder reference")
                if current.parent_folder:
                    current = current.parent_folder
                else:
                    break
        
        # Validate group requirement
        if self.access_type == 'group' and not self.group:
            raise ValidationError("Group is required when access type is 'group'")
        
        if self.access_type != 'group' and self.group:
            raise ValidationError("Group should only be set when access type is 'group'")
        
        # NEW: Validate parent-child access type compatibility
        self._validate_parent_child_access()
    
    def _validate_parent_child_access(self):
        """Validate that parent-child folder access types are logically compatible"""
        
        # Check parent folder restrictions
        if self.parent_folder:
            parent = Folder.objects.get(pk=self.parent_folder.pk)
            
            # Rule 1: Private parent cannot have public children
            if parent.access_type == 'private' and self.access_type == 'public':
                raise ValidationError(
                    f"Cannot create public folder inside private folder '{parent.name}'. "
                    "Public folders should not be hidden inside private folders."
                )
            
            # Rule 2: Private parent cannot have group children (unless same user is in group)
            if parent.access_type == 'private' and self.access_type == 'group':
                if not (self.group and parent.created_by and parent.created_by.groups.filter(id=self.group.id).exists()):
                    raise ValidationError(
                        f"Cannot create group folder inside private folder '{parent.name}' "
                        f"unless the folder owner is a member of group '{self.group.name if self.group else 'Unknown'}'."
                    )
            
            # Rule 3: Group parent should contain compatible children
            if parent.access_type == 'group' and self.access_type == 'group':
                if parent.group != self.group:
                    raise ValidationError(
                        f"Group folder inside group folder '{parent.name}' should use the same group "
                        f"(parent: '{parent.group.name}', child: '{self.group.name if self.group else 'None'}')."
                    )
        
        # Check children restrictions when changing existing folder
        if self.pk:  # Only for existing folders
            self._validate_existing_children()
    
    def _validate_existing_children(self):
        """Validate that existing children are compatible with new access type"""
        children = self.children.all()
        
        if self.access_type == 'private':
            # Private folders cannot have public children
            public_children = children.filter(access_type='public')
            if public_children.exists():
                child_names = ', '.join([child.name for child in public_children[:3]])
                if public_children.count() > 3:
                    child_names += f' and {public_children.count() - 3} more'
                raise ValidationError(
                    f"Cannot make folder private because it contains public subfolders: {child_names}. "
                    "Please change the child folders first."
                )
            
            # Private folders cannot have group children (unless owner is in those groups)
            if self.created_by:
                user_groups = self.created_by.groups.all()
                incompatible_group_children = children.filter(
                    access_type='group'
                ).exclude(group__in=user_groups)
                
                if incompatible_group_children.exists():
                    child_names = ', '.join([f"{child.name} ({child.group.name})" for child in incompatible_group_children[:3]])
                    if incompatible_group_children.count() > 3:
                        child_names += f' and {incompatible_group_children.count() - 3} more'
                    raise ValidationError(
                        f"Cannot make folder private because it contains group subfolders you don't belong to: {child_names}. "
                        "Please change the child folders first or ensure you're a member of those groups."
                    )
        
        if self.access_type == 'group' and self.group:
            # Group folders should have compatible group children
            incompatible_group_children = children.filter(
                access_type='group'
            ).exclude(group=self.group)
            
            if incompatible_group_children.exists():
                child_names = ', '.join([f"{child.name} ({child.group.name})" for child in incompatible_group_children[:3]])
                if incompatible_group_children.count() > 3:
                    child_names += f' and {incompatible_group_children.count() - 3} more'
                raise ValidationError(
                    f"Cannot change to group '{self.group.name}' because it contains subfolders from different groups: {child_names}. "
                    "Please change the child folders first."
                )
    
    def get_path(self):
        """Get folder path like 'Root/Sub1/Sub2'"""
        path = [self.name]
        current = self.parent_folder
        while current:
            path.insert(0, current.name)
            current = current.parent_folder
        return " / ".join(path)
    
    def get_full_path_with_access(self):
        """Get path with access type info"""
        access_suffix = {
            'private': ' [Private]',
            'public': ' [Public]',
            'group': f' [Group: {self.group.name if self.group else "None"}]'
        }
        return self.get_path() + access_suffix.get(self.access_type, '')
    
    def user_can_access(self, user):
        """Check if user can access this folder based on access type"""
        if self.access_type == 'private':
            return self.created_by == user
        elif self.access_type == 'public':
            return True  # Everyone can access public folders
        elif self.access_type == 'group':
            return self.group and self.group in user.groups.all()
        return False
    
    def get_access_description(self):
        """Human-readable access description"""
        if self.access_type == 'private':
            return f"Private folder by {self.created_by.username if self.created_by else 'Unknown'}"
        elif self.access_type == 'public':
            return "Public folder - accessible by everyone"
        elif self.access_type == 'group':
            return f"Group folder - accessible by '{self.group.name if self.group else 'No Group'}' members"
        return "Unknown access type"
    
    @classmethod
    def get_user_accessible_folders(cls, user):
        """Get all folders user can access"""
        from django.db.models import Q
        
        user_groups = user.groups.all()
        
        return cls.objects.filter(
            Q(access_type='private', created_by=user) |  # User's private folders
            Q(access_type='public') |  # Public folders
            Q(access_type='group', group__in=user_groups)  # Group folders user belongs to
        ).distinct()

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