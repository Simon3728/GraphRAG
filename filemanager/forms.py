from django import forms
from django.contrib.auth.models import Group
from .models import UploadedDocument, Folder


class SimpleUploadForm(forms.ModelForm):
    """Simple upload form - user auto-populated"""
    
    class Meta:
        model = UploadedDocument
        fields = ['file', 'folder']
        widgets = {
            'file': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.pdf,.docx,.doc,.pptx,.xlsx,.txt,.md,.csv,.json,.py,.js,.html,.xml'
            }),
            'folder': forms.Select(attrs={
                'class': 'form-select'
            })
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user:
            # Only show folders from groups user belongs to
            user_groups = user.groups.all()
            self.fields['folder'].queryset = Folder.objects.filter(
                group__in=user_groups
            ).select_related('group', 'parent_folder').order_by('group__name', 'name')
            self.fields['folder'].empty_label = "📁 Root (no folder)"
            
            # Add help text showing available groups
            group_names = [group.name for group in user_groups]
            self.fields['folder'].help_text = f"Available groups: {', '.join(group_names)}"


class FolderForm(forms.ModelForm):
    """Simple folder form - user auto-populated"""
    
    class Meta:
        model = Folder
        fields = ['name', 'description', 'parent_folder', 'group']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter folder name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 3,
                'placeholder': 'Optional description of this folder'
            }),
            'parent_folder': forms.Select(attrs={
                'class': 'form-select'
            }),
            'group': forms.Select(attrs={
                'class': 'form-select'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user:
            # Only show groups user belongs to and accessible folders
            user_groups = user.groups.all()
            self.fields['group'].queryset = user_groups
            self.fields['parent_folder'].queryset = Folder.objects.filter(
                group__in=user_groups
            ).select_related('group', 'parent_folder').order_by('group__name', 'name')
            self.fields['parent_folder'].empty_label = "📁 No parent (root level)"
            
            # Set default group if user has personal group
            personal_group = user_groups.filter(name='personal').first()
            if personal_group and not self.initial.get('group'):
                self.initial['group'] = personal_group
    
    def clean(self):
        """Validate folder creation"""
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        parent_folder = cleaned_data.get('parent_folder')
        group = cleaned_data.get('group')
        
        if name and parent_folder and group:
            # Check if folder with same name exists in same parent and group
            existing = Folder.objects.filter(
                name=name,
                parent_folder=parent_folder,
                group=group
            ).exclude(pk=self.instance.pk if self.instance else None)
            
            if existing.exists():
                raise forms.ValidationError(
                    f"A folder named '{name}' already exists in this location for the group '{group.name}'."
                )
        
        return cleaned_data


class DocumentSearchForm(forms.Form):
    """Form for searching and filtering documents"""
    
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search documents...',
            'autocomplete': 'off'
        })
    )
    
    file_type = forms.ChoiceField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    group = forms.ModelChoiceField(
        queryset=Group.objects.none(),
        required=False,
        empty_label="All groups",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All statuses')] + UploadedDocument.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    folder = forms.ModelChoiceField(
        queryset=Folder.objects.none(),
        required=False,
        empty_label="All folders",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user:
            user_groups = user.groups.all()
            
            # Set group choices
            self.fields['group'].queryset = user_groups
            
            # Set folder choices
            self.fields['folder'].queryset = Folder.objects.filter(
                group__in=user_groups
            ).select_related('group').order_by('group__name', 'name')
            
            # Set file type choices based on user's documents
            file_types = UploadedDocument.objects.filter(
                group__in=user_groups
            ).values_list('file_type', flat=True).distinct()
            
            type_choices = [('', 'All types')]
            for file_type in sorted(set(file_types)):
                if file_type:
                    type_choices.append((file_type, file_type.title()))
            
            self.fields['file_type'].choices = type_choices


class BulkActionForm(forms.Form):
    """Form for bulk actions on documents"""
    
    ACTION_CHOICES = [
        ('', 'Select action...'),
        ('move_to_folder', 'Move to folder'),
        ('change_group', 'Change group'),
        ('mark_for_reprocessing', 'Mark for reprocessing'),
        ('delete', 'Delete'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    target_folder = forms.ModelChoiceField(
        queryset=Folder.objects.none(),
        required=False,
        empty_label="Root (no folder)",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    target_group = forms.ModelChoiceField(
        queryset=Group.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    selected_documents = forms.CharField(
        widget=forms.HiddenInput()
    )
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user:
            user_groups = user.groups.all()
            self.fields['target_folder'].queryset = Folder.objects.filter(
                group__in=user_groups
            ).order_by('name')
            self.fields['target_group'].queryset = user_groups
    
    def clean_selected_documents(self):
        """Validate document IDs"""
        doc_ids = self.cleaned_data['selected_documents']
        if not doc_ids:
            raise forms.ValidationError("No documents selected.")
        
        try:
            ids = [int(doc_id) for doc_id in doc_ids.split(',') if doc_id.strip()]
            if not ids:
                raise forms.ValidationError("No valid document IDs found.")
            return ids
        except ValueError:
            raise forms.ValidationError("Invalid document IDs.")
    
    def clean(self):
        """Validate action requirements"""
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        target_folder = cleaned_data.get('target_folder')
        target_group = cleaned_data.get('target_group')
        
        if action == 'move_to_folder' and target_folder is None:
            # Allow moving to root (target_folder = None is valid)
            pass
        elif action == 'change_group' and not target_group:
            raise forms.ValidationError("Please select a target group.")
        
        return cleaned_data


class DocumentEditForm(forms.ModelForm):
    """Form for editing document metadata"""
    
    class Meta:
        model = UploadedDocument
        fields = ['title', 'folder', 'group']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Document title'
            }),
            'folder': forms.Select(attrs={
                'class': 'form-select'
            }),
            'group': forms.Select(attrs={
                'class': 'form-select'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user:
            user_groups = user.groups.all()
            self.fields['folder'].queryset = Folder.objects.filter(
                group__in=user_groups
            ).order_by('name')
            self.fields['folder'].empty_label = "Root (no folder)"
            self.fields['group'].queryset = user_groups


class FolderEditForm(forms.ModelForm):
    """Form for editing folder metadata"""
    
    class Meta:
        model = Folder
        fields = ['name', 'description', 'parent_folder', 'group']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3
            }),
            'parent_folder': forms.Select(attrs={
                'class': 'form-select'
            }),
            'group': forms.Select(attrs={
                'class': 'form-select'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user:
            user_groups = user.groups.all()
            
            # Exclude current folder from parent choices to prevent circular reference
            parent_queryset = Folder.objects.filter(group__in=user_groups)
            if self.instance and self.instance.pk:
                parent_queryset = parent_queryset.exclude(pk=self.instance.pk)
            
            self.fields['parent_folder'].queryset = parent_queryset.order_by('name')
            self.fields['parent_folder'].empty_label = "No parent (root level)"
            self.fields['group'].queryset = user_groups
    
    def clean(self):
        """Validate folder edit"""
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        parent_folder = cleaned_data.get('parent_folder')
        group = cleaned_data.get('group')
        
        if name and group:
            # Check for duplicate names in same parent and group
            existing = Folder.objects.filter(
                name=name,
                parent_folder=parent_folder,
                group=group
            ).exclude(pk=self.instance.pk if self.instance else None)
            
            if existing.exists():
                raise forms.ValidationError(
                    f"A folder named '{name}' already exists in this location for the group '{group.name}'."
                )
        
        return cleaned_data