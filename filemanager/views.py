from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, Http404
from django.db.models import Q
from django.utils import timezone
from .models import UploadedDocument, Folder, ProcessingLog, UserVectorstoreManager
from .forms import SimpleUploadForm, FolderForm
import os


@login_required
def simple_upload(request):
    """Simple upload - auto-populate user"""
    if request.method == 'POST':
        form = SimpleUploadForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            document = form.save(commit=False)
            document.uploaded_by = request.user
            
            # Auto-set group if no folder selected
            if not document.folder:
                # Try to get user's personal group (or first group)
                personal_group = request.user.groups.filter(name='personal').first()
                if not personal_group:
                    personal_group = request.user.groups.first()
                
                if not personal_group:
                    messages.error(request, "You don't belong to any groups. Please contact admin.")
                    return render(request, 'documents/simple_upload.html', {'form': form})
                
                document.group = personal_group
            
            document.save()
            
            ProcessingLog.objects.create(
                document=document,
                status='info',
                message=f'Document "{document.title}" uploaded successfully'
            )
            
            # TODO: Trigger LlamaIndex processing AND user vectorstore update
            # process_document_and_update_user_vectorstore.delay(document.id, request.user.id)
            
            messages.success(request, f'"{document.title}" uploaded! Processing will start shortly.')
            return redirect('document_list')
    else:
        form = SimpleUploadForm(user=request.user)
    
    return render(request, 'documents/simple_upload.html', {'form': form})


@login_required
def create_folder(request):
    """Create folder - auto-populate user"""
    parent_id = request.GET.get('parent')
    parent_folder = None
    
    if parent_id:
        try:
            parent_folder = Folder.objects.get(
                id=parent_id,
                group__in=request.user.groups.all()
            )
        except Folder.DoesNotExist:
            messages.error(request, "Parent folder not found.")
            return redirect('document_list')
    
    if request.method == 'POST':
        form = FolderForm(request.POST, user=request.user)
        if form.is_valid():
            folder = form.save(commit=False)
            folder.created_by = request.user
            folder.parent_folder = parent_folder
            folder.save()
            
            messages.success(request, f'Folder "{folder.name}" created!')
            return redirect('folder_view', folder_id=folder.id)
    else:
        form = FolderForm(user=request.user)
        if parent_folder:
            form.initial['group'] = parent_folder.group
    
    return render(request, 'documents/create_folder.html', {
        'form': form,
        'parent_folder': parent_folder
    })


@login_required 
def document_list(request):
    """Show all documents user can access"""
    user_groups = request.user.groups.all()
    documents = UploadedDocument.objects.filter(
        group__in=user_groups
    ).select_related('group', 'folder', 'uploaded_by').order_by('-uploaded_at')
    
    # Search functionality
    search = request.GET.get('search')
    if search:
        documents = documents.filter(
            Q(title__icontains=search) |
            Q(description__icontains=search) |
            Q(original_filename__icontains=search)
        )
    
    # Filter by file type
    file_type = request.GET.get('file_type')
    if file_type:
        documents = documents.filter(file_type=file_type)
    
    # Filter by group
    group_id = request.GET.get('group')
    if group_id:
        documents = documents.filter(group_id=group_id)
    
    # Filter by status
    status = request.GET.get('status')
    if status:
        documents = documents.filter(processing_status=status)
    
    # Get folders for navigation
    folders = Folder.objects.filter(
        group__in=user_groups,
        parent_folder__isnull=True
    ).order_by('name')
    
    context = {
        'documents': documents,
        'folders': folders,
        'user_vectorstore_name': UserVectorstoreManager.get_user_vectorstore_name(request.user),
        'search': search,
        'file_type': file_type,
        'group_id': group_id,
        'status': status,
        'user_groups': user_groups,
    }
    
    return render(request, 'documents/document_list.html', context)


@login_required
def folder_view(request, folder_id=None):
    """View folder contents"""
    user_groups = request.user.groups.all()
    
    if folder_id:
        folder = get_object_or_404(
            Folder,
            id=folder_id,
            group__in=user_groups
        )
        documents = folder.documents.filter(group__in=user_groups)
        subfolders = folder.children.filter(group__in=user_groups)
        breadcrumbs = folder.get_breadcrumbs() if hasattr(folder, 'get_breadcrumbs') else []
    else:
        # Root level
        folder = None
        documents = UploadedDocument.objects.filter(
            group__in=user_groups,
            folder__isnull=True
        )
        subfolders = Folder.objects.filter(
            group__in=user_groups,
            parent_folder__isnull=True
        )
        breadcrumbs = []
    
    context = {
        'folder': folder,
        'documents': documents.order_by('-uploaded_at'),
        'subfolders': subfolders.order_by('name'),
        'breadcrumbs': breadcrumbs,
        'can_edit': True,  # All logged in users can create folders/upload
    }
    
    return render(request, 'documents/folder_view.html', context)


@login_required
def document_detail(request, pk):
    """View document details"""
    user_groups = request.user.groups.all()
    document = get_object_or_404(
        UploadedDocument,
        pk=pk,
        group__in=user_groups
    )
    
    # Get processing logs
    logs = document.logs.all()[:10]  # Last 10 logs
    
    # Get chunks preview
    chunks = document.chunks.all()[:5]  # First 5 chunks
    
    context = {
        'document': document,
        'logs': logs,
        'chunks': chunks,
        'can_edit': document.uploaded_by == request.user,
    }
    
    return render(request, 'documents/document_detail.html', context)


@login_required
def download_document(request, pk):
    """Download document file"""
    user_groups = request.user.groups.all()
    document = get_object_or_404(
        UploadedDocument,
        pk=pk,
        group__in=user_groups
    )
    
    if os.path.exists(document.file.path):
        with open(document.file.path, 'rb') as fh:
            response = HttpResponse(fh.read(), content_type=document.mime_type)
            response['Content-Disposition'] = f'attachment; filename="{document.original_filename}"'
            return response
    
    raise Http404("File not found")


@login_required
def preview_document(request, pk):
    """Preview document content (for text files)"""
    user_groups = request.user.groups.all()
    document = get_object_or_404(
        UploadedDocument,
        pk=pk,
        group__in=user_groups
    )
    
    # Check if file can be previewed
    previewable_types = ['txt', 'markdown', 'csv', 'json', 'python', 'javascript', 'html']
    if document.file_type not in previewable_types:
        messages.error(request, "This file type cannot be previewed.")
        return redirect('document_detail', pk=pk)
    
    try:
        with open(document.file.path, 'r', encoding='utf-8') as f:
            content = f.read()[:10000]  # Limit preview to first 10KB
    except Exception as e:
        messages.error(request, f"Error reading file: {str(e)}")
        return redirect('document_detail', pk=pk)
    
    context = {
        'document': document,
        'content': content
    }
    
    return render(request, 'documents/preview.html', context)


@login_required
def delete_document(request, pk):
    """Delete document"""
    user_groups = request.user.groups.all()
    document = get_object_or_404(
        UploadedDocument,
        pk=pk,
        group__in=user_groups
    )
    
    # Only allow deletion if user uploaded it or is in personal group
    can_delete = (
        document.uploaded_by == request.user or 
        document.group.name == 'personal'
    )
    
    if not can_delete:
        messages.error(request, "You don't have permission to delete this document.")
        return redirect('document_detail', pk=pk)
    
    if request.method == 'POST':
        document_title = document.title
        document.delete()
        messages.success(request, f'Document "{document_title}" deleted successfully.')
        return redirect('document_list')
    
    return render(request, 'documents/confirm_delete.html', {'document': document})


@login_required
def delete_folder(request, pk):
    """Delete folder and its contents"""
    user_groups = request.user.groups.all()
    folder = get_object_or_404(
        Folder,
        pk=pk,
        group__in=user_groups
    )
    
    # Only allow deletion if user created it or is in personal group
    can_delete = (
        folder.created_by == request.user or 
        folder.group.name == 'personal'
    )
    
    if not can_delete:
        messages.error(request, "You don't have permission to delete this folder.")
        return redirect('folder_view', folder_id=pk)
    
    if request.method == 'POST':
        folder_name = folder.name
        parent_folder = folder.parent_folder
        folder.delete()  # CASCADE will delete contents
        messages.success(request, f'Folder "{folder_name}" deleted successfully.')
        
        if parent_folder:
            return redirect('folder_view', folder_id=parent_folder.id)
        else:
            return redirect('document_list')
    
    # Count contents for confirmation
    total_documents = folder.documents.count()
    total_subfolders = folder.children.count()
    
    context = {
        'folder': folder,
        'total_documents': total_documents,
        'total_subfolders': total_subfolders,
    }
    
    return render(request, 'documents/confirm_delete_folder.html', context)
